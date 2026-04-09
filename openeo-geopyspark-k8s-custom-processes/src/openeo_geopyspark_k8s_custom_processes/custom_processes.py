"""
openeo-geopyspark-driver plugin to load/add custom processes

loaded automatically by `openeogeotrellis.deploy.load_custom_processes`
"""

import base64
import json
import logging
import os
import re
import textwrap
from copy import deepcopy
from pathlib import Path
from typing import Union, List

import kubernetes.config
from kubernetes.config.incluster_config import SERVICE_TOKEN_FILENAME

from openeo_driver.backend import LoadParameters
from openeo_driver.datacube import DriverDataCube
from openeo_driver.datastructs import SarBackscatterArgs
from openeo_driver.dry_run import DryRunDataTracer, DataSource
from openeo_driver.processes import ProcessArgs
from openeo_driver.ProcessGraphDeserializer import (
    ENV_DRY_RUN_TRACER,
    ProcessSpec,
    non_standard_process,
    process_registry_2xx,
    process_registry_100, _extract_load_parameters,
)
from openeo_driver.specs import read_spec
from openeo_driver.utils import EvalEnv
import openeogeotrellis.integrations.stac
from openeogeotrellis.integrations.calrissian import CalrissianJobLauncher, CwLSource, find_stac_root
from openeogeotrellis.util.runtime import get_job_id, get_request_id
import openeogeotrellis.load_stac
from openeogeotrellis.stac_save_result import StacSaveResult

log = logging.getLogger("openeo_geopyspark_k8s_custom_processes")
log.info(f"Loading custom processes from {__file__}")


CWL_ROOT = Path(__file__).parent / "cwl"


def _ensure_kubernetes_config():
    # TODO: better place to load this config?
    if os.path.exists(SERVICE_TOKEN_FILENAME):
        kubernetes.config.load_incluster_config()
    else:
        kubernetes.config.load_kube_config()


@non_standard_process(
    ProcessSpec(id="_cwl_demo_hello", description="Proof-of-concept process to run CWL based processing.")
    .param(name="name", description="Name to greet.", schema={"type": "string"}, required=False)
    .returns(description="data", schema={"type": "string"})
)
def _cwl_demo_hello(args: ProcessArgs, env: EvalEnv):
    """Proof of concept openEO process to run CWL based processing"""
    name = args.get_optional(
        "name",
        default="World",
        validator=ProcessArgs.validator_generic(
            # TODO: helper to create regex based validator
            lambda n: bool(re.fullmatch("^[a-zA-Z]+$", n)),
            error_message="Must be a simple name, but got {actual!r}.",
        ),
    )

    if env.get(ENV_DRY_RUN_TRACER):
        return "dummy"

    _ensure_kubernetes_config()

    cwl_source = CwLSource.from_path(CWL_ROOT / "hello.cwl")
    correlation_id = get_job_id(default=None) or get_request_id(default=None)
    cwl_arguments = [
        "--message",
        f"Hello {name}, greetings from {correlation_id}.",
    ]

    launcher = CalrissianJobLauncher.from_context(env)
    results = launcher.run_cwl_workflow(
        cwl_source=cwl_source,
        cwl_arguments=cwl_arguments,
    )

    for k, v in results.items():
        log.info(f"_cwl_demo_hello result {k!r} at pre-signed URL {v.generate_presigned_url()}")

    return results["output.txt"].read(encoding="utf8")


def cwl_common_to_stac(
    cwl_arguments: Union[List[str], dict],
    env: EvalEnv,
    cwl_source: CwLSource,
    stac_root: str = "collection.json",
    direct_s3_mode=False,
) -> str:
    dry_run_tracer: DryRunDataTracer = env.get(ENV_DRY_RUN_TRACER)
    if dry_run_tracer:
        # TODO: use something else than `dry_run_tracer.load_stac`
        #       to avoid risk on conflict with "regular" load_stac code flows?
        return "dummy"

    _ensure_kubernetes_config()

    log.info(f"Loading CWL from {cwl_source=}")

    launcher = CalrissianJobLauncher.from_context(env)
    results = launcher.run_cwl_workflow(
        cwl_source=cwl_source,
        cwl_arguments=cwl_arguments,
    )

    # TODO: provide generic helper to log some info about the results
    for k, v in results.items():
        log.info(f"result {k!r}: {v.generate_public_url()=} {v.generate_presigned_url()=}")

    try:
        stac_root_new = find_stac_root(results.keys(), stac_root)
        if stac_root_new:
            stac_root = stac_root_new
    except Exception as e:
        log.warning(f"Error from find_stac_root {stac_root!r}: {e}")

    if direct_s3_mode:
        collection_url = results[stac_root].s3_uri()
    else:
        collection_url = results[stac_root].generate_public_url()
    return collection_url


def cwl_common(
    cwl_arguments: Union[List[str], dict],
    env: EvalEnv,
    cwl_source: CwLSource,
    stac_root: str = "collection.json",
    direct_s3_mode=False,
) -> DriverDataCube:
    collection_url = cwl_common_to_stac(
        cwl_arguments,
        env,
        cwl_source,
        stac_root,
        direct_s3_mode,
    )

    load_stac_dummy_url = "dummy"
    dry_run_tracer: DryRunDataTracer = env.get(ENV_DRY_RUN_TRACER)
    if dry_run_tracer:
        # TODO: use something else than `dry_run_tracer.load_stac`
        #       to avoid risk on conflict with "regular" load_stac code flows?
        return dry_run_tracer.load_stac(url=load_stac_dummy_url, arguments={})

    if direct_s3_mode:
        load_stac_kwargs = {"stac_io": openeogeotrellis.integrations.stac.S3StacIO()}
    else:
        load_stac_kwargs = {}

    source_id = DataSource.load_stac(
        load_stac_dummy_url, properties={}, bands=[], env=env
    ).get_source_id()
    load_params = _extract_load_parameters(env, source_id=source_id)

    env = env.push(
        {
            # TODO: this is apparently necessary to set explicitly, but shouldn't this be the default?
            "pyramid_levels": "highest",
        }
    )
    return openeogeotrellis.load_stac.load_stac(
        url=collection_url,
        load_params=load_params,
        env=env,
        **load_stac_kwargs,
    )


@non_standard_process(
    ProcessSpec(
        id="_cwl_dummy_stac",
        description="Proof-of-concept process to run CWL based processing, and load the result as data cube.",
    )
    .param(name="direct_s3_mode", description="direct_s3_mode", schema={"type": "boolean"}, required=False)
    .returns(description="data", schema={"type": "object", "subtype": "datacube"})
)
def _cwl_dummy_stac(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    """
    Proof of concept openEO process to run CWL based processing:
    CWL produces a local STAC collection,
    that is then loaded `load_stac`-style as a `GeopysparkDataCube`.
    """
    cwl_source = CwLSource.from_path(CWL_ROOT / "dummy_stac.cwl")
    cwl_arguments: List[str] = []
    direct_s3_mode = args.get_optional("direct_s3_mode", default=False)
    return cwl_common(cwl_arguments, env, cwl_source, direct_s3_mode=direct_s3_mode)


@non_standard_process(
    ProcessSpec(
        id="_cwl_dummy_stac_to_stac",
        description="Proof-of-concept process to run CWL based processing, and load the result as data cube.",
    )
    .param(name="direct_s3_mode", description="direct_s3_mode", schema={"type": "boolean"}, required=False)
    .returns(description="data", schema={"type": "object", "subtype": "datacube"})
)
def _cwl_dummy_stac_to_stac(args: ProcessArgs, env: EvalEnv) -> StacSaveResult:
    """
    Proof of concept openEO process to run CWL based processing:
    CWL produces a local STAC collection,
    that is then loaded `load_stac`-style as a `GeopysparkDataCube`.
    """
    cwl_source = CwLSource.from_path(CWL_ROOT / "dummy_stac.cwl")
    cwl_arguments: List[str] = []
    direct_s3_mode = args.get_optional("direct_s3_mode", default=False)
    stac_root = cwl_common_to_stac(cwl_arguments, env, cwl_source, direct_s3_mode=direct_s3_mode)
    return StacSaveResult(stac_root)


@non_standard_process(
    ProcessSpec(
        id="_cwl_dummy_stac_parallel",
        description="Proof-of-concept process to run CWL in parallel.",
    )
    .param(
        name="request_dates",
        description="request_dates. Choose from 2023-06-01, 2023-06-04 and / or 2023-06-04.",
        schema={
            "type": "array",
            "subtype": "temporal-intervals",
            "minItems": 1,
            "items": {
                "anyOf": [
                    {
                        "type": "string",
                        "format": "date-time",
                        "subtype": "date-time",
                        "description": "Date and time with a time zone.",
                    },
                    {
                        "type": "string",
                        "format": "date",
                        "subtype": "date",
                        "description": "Date only, formatted as `YYYY-MM-DD`. The time zone is UTC. Missing time components are all 0.",
                    },
                    {
                        "type": "string",
                        "subtype": "time",
                        "pattern": "^\\d{2}:\\d{2}:\\d{2}$",
                        "description": "Time only, formatted as `HH:MM:SS`. The time zone is UTC.",
                    },
                    {"type": "null"},
                ]
            },
        },
        required=True,
    )
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def _cwl_dummy_stac_parallel(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    cwl_arguments = []
    request_dates = args.get_required("request_dates", expected_type=list)
    for date in request_dates:
        cwl_arguments.extend(["--request_dates", date])
    return cwl_common(
        cwl_arguments,
        env,
        cwl_source=CwLSource.from_path(CWL_ROOT / "scatter-gather-stac.cwl"),
    )


def insar_common(
    kwargs: dict, env: EvalEnv, cwl_url: str, stac_root: str = "S1_2images_collection.json"
) -> DriverDataCube:
    if "InSAR_pairs" in kwargs:
        primary_dates = [pair[0] for pair in kwargs["InSAR_pairs"]]
        primary_dates_duplicates = set([d for d in primary_dates if primary_dates.count(d) > 1])
        if primary_dates_duplicates:
            raise ValueError(
                f"Duplicate primary date(s) found in InSAR_pairs: {primary_dates_duplicates}. "
                "You can load multiple primary dates over multiple processes if needed."
            )
    input_base64_json = base64.b64encode(json.dumps(kwargs).encode("utf8")).decode("ascii")
    cwl_arguments = ["--input_base64_json", input_base64_json]
    return cwl_common(cwl_arguments, env, CwLSource.from_url(cwl_url), stac_root)


@non_standard_process(
    ProcessSpec(
        id="sar_coherence",
        description=textwrap.dedent(
            """
        This process computes the Interferometric Coherence for a series of Sentinel-1 bursts, allowing to specify custom sizes of the coherence window by setting the coherence_window_ax and coherence_window_rg parameters. It requires you to provide the temporal_extent for the period of interest, the temporal_baseline (6, 12 or more days), the burst_id and sub_swath to select the Sentinel-1 burst of interest.
        The implementation is based on SNAP and defined as a CWL (Common Workflow Language) available here: [sar_coherence_parallel_temporal_extent.cwl](https://github.com/cloudinsar/s1-workflows/blob/main/cwl/sar_coherence_parallel_temporal_extent.cwl)
        <https://www.eurac.edu/en/projects/cloudinsar>.

        An example on how to use it:

        ```python
        datacube = connection.datacube_from_process(
            process_id="sar_coherence",
            temporal_extent=["2018-01-28", "2018-02-03"],
            temporal_baseline=6,
            burst_id=329488,
            polarization="VH",
            sub_swath="IW2",
        )
        datacube = datacube.filter_bbox(west=-6.15702, south=37.07256, east=-6.01368, north=37.17057)
        datacube = datacube.save_result(format="GTiff")

        job = datacube.create_job(title="sar_coherence test")
        job.start_and_wait()
        job.get_results().download_files()
        ```
        """
        ).strip(),
    )
    .param(
        name="temporal_extent",
        description="temporal_extent",
        schema={
            "type": "array",
            "subtype": "temporal-interval",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "string",
                "format": "date",
                "subtype": "date",
                "description": "Date only, formatted as `YYYY-MM-DD`. The time zone is UTC.",
            },
        },
        required=True,
    )
    .param(
        name="temporal_extent",
        description="Specifies area where to search for bursts. If multiple bursts are found, the one with the lowest id number will be selected. This parameter can be used instead of `burst_id`.",
        schema={
            "title": "Bounding Box",
            "type": "object",
            "subtype": "bounding-box",
            "required": ["west", "south", "east", "north"],
            "properties": {
                "west": {"description": "West (lower left corner, coordinate axis 1).", "type": "number"},
                "south": {"description": "South (lower left corner, coordinate axis 2).", "type": "number"},
                "east": {"description": "East (upper right corner, coordinate axis 1).", "type": "number"},
                "north": {"description": "North (upper right corner, coordinate axis 2).", "type": "number"},
            },
        },
        required=False,
    )
    .param(
        name="temporal_baseline",
        description="Should be a multiple of 6. This is used to select how many days the secondary date will be after the primary for each date pair.",
        schema={"type": "integer", "minimum": 6},
        required=True,
    )
    .param(
        name="burst_id",
        description=(
            """
            A temporal extent could have multiple bursts per day. Use [this notebook](https://github.com/cloudinsar/s1-workflows/blob/main/notebooks/LPS_DEMO/Input_selection.ipynb) to find a fitting `burst_id`.
            Alternatively, the burst id map can be downloaded here: [Burst ID Maps 2022-05-30](https://sar-mpc.eu/files/S1_burstid_20220530.zip).
            You can also specify `temporal_extent` instead, so that a `burst_id` gets automatically selected.
            """
        ).strip(),
        schema={"type": "integer", "minimum": 0},
        required=False,
    )
    .param(
        name="coherence_window_az",
        description="coherence_window_az",
        schema={"type": "integer", "minimum": 0},
        required=False,
    )
    .param(
        name="coherence_window_rg",
        description="coherence_window_rg",
        schema={"type": "integer", "minimum": 0},
        required=False,
    )
    .param(
        name="polarization",
        description="polarization",
        schema={"type": "string", "enum": ["VV", "VH", "HH", "HV"]},
        required=True,
    )
    .param(
        name="sub_swath",
        description="sub_swath",
        schema={"type": "string", "enum": ["IW1", "IW2", "IW3", "EW1", "EW2", "EW3", "EW4", "EW5"]},
        required=True,
    )
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def sar_coherence(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/sar_coherence_parallel_temporal_extent.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="sar_coherence_parallel",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(
        name="InSAR_pairs",
        description="InSAR_pairs",
        schema={
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        required=True,
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="coherence_window_az", description="coherence_window_az", schema={"type": "integer"}, required=False)
    .param(name="coherence_window_rg", description="coherence_window_rg", schema={"type": "integer"}, required=False)
    .param(name="polarization", description="polarization", schema={"type": "string"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def sar_coherence_parallel(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/sar_coherence_parallel.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="sar_interferogram",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(
        name="InSAR_pairs",
        description="InSAR_pairs",
        schema={
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        required=True,
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="coherence_window_az", description="coherence_window_az", schema={"type": "integer"}, required=False)
    .param(name="coherence_window_rg", description="coherence_window_rg", schema={"type": "integer"}, required=False)
    .param(name="n_az_looks", description="n_az_looks", schema={"type": "integer"}, required=False)
    .param(name="n_rg_looks", description="n_rg_looks", schema={"type": "integer"}, required=False)
    .param(name="polarization", description="polarization", schema={"type": "string"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def sar_interferogram(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/sar_interferogram.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="sar_slc_preprocessing",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(
        name="temporal_extent",
        description="temporal_extent",
        schema={"type": "array", "items": {"type": "string"}},
        required=True,
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="primary_date", description="primary_date", schema={"type": "string"}, required=True)
    .param(
        name="polarization",
        description="polarization",
        schema={"type": "array", "items": {"type": "string"}},
        required=True,
    )
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=False)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def sar_slc_preprocessing(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/sar_slc_preprocessing.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="force_level2",
        description="FORCE Level 2 ARD generation process. "
                    "More info here: https://github.com/bcdev/apex-force-openeo . "
                    "Parameter documentation in https://force-eo.readthedocs.io/en/latest/howto/l2-ard.html#tut-ard "
                    "and https://force-eo.readthedocs.io/en/latest/howto/datacube.html#tut-datacube",
    )
    .param(name="name",
           description="Name of the datacube. Example: bologna . Default: cube-<timestamp>",
           schema={"type": "string"},
           required=False)
    .param(name="aoi",
           description='Area of interest as geojson feature, extent of the resulting cube. Example: '
                       '{ "type": "Feature", "geometry": { "type": "Polygon", '
                       '"coordinates": [[[10.5,44.0],[10.5,45.0],[11.5,45.0],[11.5,44.0],[10.5,44.0]]] }, '
                       '"properties": { "name": "Bologna" } } . Default: not set, '
                       'extent determined by inputs',
           schema={"type": "string"},
           required=False)
    .param(name="tile_size",
           description="Tile size (in target units, commonly in meters) of the gridded output. tiles are square. "
                       "Not used if projection is one of the predefined projections. Default: 30000",
           schema={"type": "integer"},
           required=False)
    .param(name="block_size",
           description="Block size (in target units, commonly in meters) of the image chips. Blocks are stripes, "
                       "i.e. they are as wide as the tile and as high as specified here. "
                       "Not used if projection is one of the predefined projections. Default: 3000",
           schema={"type": "integer"},
           required=False)
    .param(name="origin_lon",
           description="Origin coordinate of the grid system in decimal degree (negative values for West/South). "
                       "The upper left corner of tile X0000_Y0000 represents this point. It is a good choice "
                       "to use a coordinate that is North-West of your study area – to avoid negative tile numbers. "
                       "Not used if projection is one of the predefined projections. Default: -25.0",
           schema={"type": "float"},
           required=False)
    .param(name="origin_lat",
           description="Origin coordinate of the grid system in decimal degree (negative values for West/South). "
                       "The upper left corner of tile X0000_Y0000 represents this point. It is a good choice "
                       "to use a coordinate that is North-West of your study area – to avoid negative tile numbers. "
                       "Not used if projection is one of the predefined projections. Default: 60.0",
           schema={"type": "float"},
           required=False)
    .param(name="resolution",
           description="Spatial resolution in meters of the FORCE data cube. Example: 10 . Default: 20",
           schema={"type": "integer"},
           required=False)
    .param(name="projection",
           description="Defines the target coordinate system. This projection should ideally be valid for a large "
                       "geographic extent. Two default projection / grid systems are predefined in FORCE: GLANCE7 and "
                       "EQUI7. They can be specified via the projection parameter instead of giving a WKT string. The "
                       "predefined options have their own settings for origin_lat, origin_lon, tile_size, block_size, "
                       "thus values given as parameters will be ignored. EQUI7 consists of 7 Equi-Distant, "
                       "continental projections with a tile size of 100km. GLANCE7 consists of 7 Equal-Area, "
                       "continental projections, with a tile size of 150km. One datacube will be generated for "
                       "each continent. Else, the projection must be given as WKT string. You can verify your "
                       "projection (and convert to WKT from another format) using gdalsrsinfo. Default: GLANCE7",
           schema={ "anyOf": [{"type": "string", "enum": ["GLANCE7", "EQUI7"]}, {"type": "string", "description": "WKT"}]},
           required=False)
    .param(name="resampling",
           description="The resampling option for the reprojection; you can choose between Nearest Neighbor (NN), "
                       "Bilinear (BL), Cubic Convolution (CC), Cubic Spline (CSP), Lanczos (LZ), Average (AVG), "
                       "Mode (MODE), Max (MAX), Min (MIN), Median (MED), Q1 (Q1), Q3 (Q3), Sum (SUM), and "
                       "RMS (RMS). Example: NN . Default: CC",
           schema={"type": "string", "enum": ["NN", "BL", "CC", "CSP", "LZ", "AVG", "MODE", "MAX", "MIN",
                                              "MED", "Q1", "Q3", "SUM", "RMS"]},
           required=False)
    .param(name="dem",
           description="Name of digital elevation model (Copernicus_30m supported on CDSE). Default: Copernicus_30m",
           schema={"type": "string", "enum": ["Copernicus_30m"]},
           required=False)
    .param(name="do_atmo",
           description="Indicates whether atmospheric correction shall be performed. If True, Bottom-of-Atmosphere "
                       "reflectance is computed. If False, only Top-of-Atmosphere reflectance is computed. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_topo",
           description="Indicates whether topographic correction shall be performed. If True, a DEM need to be named. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_brdf",
           description="Indicates whether BRDF correction shall be performed. If True, output is nadir BRDF adjusted "
                       "reflectance instead of BOA reflectance (the output is named BOA nonetheless). "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_adjacency",
           description="Indicates whether adjacency effect correction shall be performed. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_multi_scattering",
           description="Indicates whether multiple scattering (True) or the single scattering approximation (False) shall "
                       "be used in the radiative transfer calculations. Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_aod",
           description="Indicates whether the internal AOD estimation (True) or externally generated AOD values shall "
                       "be used (False). Only True is supported on CDSE. Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="erase_clouds",
           description="Indicates whether confident cloud detections will be erased in the reflectance product, "
                       "i.e. pixels are set to nodata. The cloud flag in the QAI product will still mark these pixels "
                       "as clouds. Use this option if disk space is of concern. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="max_cloud_cover_frame",
           description="indicates whether to cancel processing of images that exceed the given threshold. The "
                       "processing will be canceled after cloud detection. Example: 99 . Default: 99",
           schema={"type": "float"},
           required=False)
    .param(name="max_cloud_cover_tile",
           description="This parameter works on a tile basis. It suppresses the output for chips (tiled image) that "
                       "exceed the given threshold. Example: 99 . Default: 99",
           schema={"type": "float"},
           required=False)
    .param(name="cloud_buffer",
           description="Buffer sizes (radius in meters) for cloud masks. Default: 300",
           schema={"type": "integer"},
           required=False)
    .param(name="cirrus_buffer",
           description="Buffer sizes (radius in meters) for cirrus masks. Default: 0",
           schema={"type": "integer"},
           required=False)
    .param(name="shadow_buffer",
           description="Buffer sizes (radius in meters) for cloud shadow masks. Default: 90",
           schema={"type": "integer"},
           required=False)
    .param(name="snow_buffer",
           description="Buffer sizes (radius in meters) for snow masks. default: 30",
           schema={"type": "integer"},
           required=False)
    .param(name="cloud_threshold",
           description="Threshold of the Fmask algorithm. Default: 0.225",
           schema={"type": "float"},
           required=False)
    .param(name="shadow_threshold",
           description="Threshold of the Fmask algorithm. Default: 0.02",
           schema={"type": "float"},
           required=False)
    .param(name="res_merge",
           description="Defines the method used for improving the spatial resolution of Sentinel-2’s 20 m bands "
                       "to 10 m. Pixels flagged as cloud or shadow will be skipped. Following methods are "
                       "available: IMPROPHE uses the ImproPhe code in a spectral-only setup; REGRESSION "
                       "uses a multi-parameter regression (results are expected to be best, but processing "
                       "time is significant); STARFM uses a spectral-only setup of the Spatial and Temporal "
                       "Adaptive Reflectance Fusion Model (prediction artifacts may occur between land cover "
                       "boundaries); NONE disables resolution merge; in this case, 20m bands are quadrupled. "
                       "Default: IMPROPHE",
           schema={"type": "string", "enum": ["IMPROPHE", "REGRESSION", "STARFM", "NONE"]},
           required=False)
    .param(name="impulse_noise",
           description="Defines whether impulse noise should be removed. Only applies to 8bit input data. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="buffer_nodata",
           description="Defines whether nodata pixels should be buffered by 1 pixel. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_format",
           description="Output format, which is either uncompressed flat binary image format aka ENVI Standard, "
                       "GeoTiff, or COG. GeoTiff images are compressed with LZW and horizontal differencing; "
                       "BigTiff support is enabled; the Tiff is structured with striped blocks according to the "
                       "TILE_SIZE (X) and BLOCK_SIZE (Y) specifications. Metadata are written to the ENVI "
                       "header or directly into the Tiff to the FORCE domain. If the size of the metadata "
                       "exceeds the Tiff's limit, an external .aux.xml file is additionally generated. Valid "
                       "values on CDSE: {GTiff, COG}",
           schema={"type": "string", "enum": ["GTiff", "COG"]},
           required=False)
    .param(name="output_dst",
           description="Indicates whether to output the cloud/cloud shadow/snow distance output. Note that this "
                       "is NOT the cloud mask (which is sitting in the mandatory QAI product). This product can "
                       "be used in force-level3; no other higher-level FORCE module is using this. "
                       "Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_aod",
           description="Indicates whether to output Aerosol Optical Depth map for the green band. No "
                       "higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_wvp",
           description="Indicates whether to output the Water Vapor map. No higher-level FORCE module is using "
                       "this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_vzn",
           description="Indicates whether to output the View Zenith map. This product can be used in force-level3; "
                       "no other higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_hot",
           description="Indicates whether to output the Haze Optimzed Transformation output. This product "
                       "can be used in force-level3; no other higher-level FORCE module is using this. "
                       "Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_ovv",
           description="Indicates whether to output overview thumbnails? These are JPEGs at reduced spatial "
                       "resolution, which feature an RGB overview + quality information overlayed (pink: cloud, "
                       "red: cirrus, cyan: cloud shadow, yellow: snow, orange: saturated, green: subzero "
                       "reflectance). No higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .returns(description="the data as a FORCE data cube",
             schema={"type": "object", "subtype": "datacube"})
)
def force_level2(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/bcdev/apex-force-openeo/refs/heads/main/material/force-l2.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="force_tsa",
        description="FORCE Time Series Analysis higher level process. "
                    "More info here: https://github.com/bcdev/apex-force-openeo . "
                    "Parameter documentation in https://force-eo.readthedocs.io/en/latest/howto/tsi.html",
    )
    .param(name="name",
           description="Name of the datacube. Example: bologna . Default: cube-<timestamp>",
           schema={"type": "string"},
           required=False)
    .param(
        name="date_range",
        description="Time extent for the analysis. All data between these dates will be used in the analysis. Format YYYY-MM-DD",
        schema={"type": "array", "items": {"type": "string"}},
        required=True,
    )
    .param(
        name="doy_range",
        description="DOY range for filtering the time extent. Day-of-Years that are outside "
                    "of the given interval will be ignored. Example: DATE_RANGE = 2010-01-01 "
                    "2019-12-31, DOY_RANGE = 91 273 will use all April-September observations "
                    "from 2010-2019. If you want to extend this window over years give "
                    "DOY min > DOY max. Example: DATE_RANGE = 2010-01-01 2019-12-31, "
                    "DOY_RANGE = 274 90 will use all October-March observations from 2010-2019. "
                    "Type: Integer list. Valid values: [1,366]. Default: 1 366",
        schema={"type": "array", "items": {"type": "integer"}},
        required=False,
    )
    .param(
        name="x_tile_range",
        description="Analysis extent, given in tile numbers (see tile naming). Each existing tile "
                    "falling into this square extent will be processed. A shapefile of the tiles "
                    "can be generated with force-tabulate-grid. Default: -999 9999",
        schema={"type": "array", "items": {"type": "integer"}},
        required=False,
    )
    .param(
        name="y_tile_range",
        description="Analysis extent, given in tile numbers (see tile naming). Each existing tile "
                    "falling into this square extent will be processed. A shapefile of the tiles "
                    "can be generated with force-tabulate-grid. Default: -999 9999",
        schema={"type": "array", "items": {"type": "integer"}},
        required=False,
    )
    .param(
        name="file_tile",
        description="Allow-list of tiles. Can be used to further limit the analysis "
                    "extent to non-square extents. The allow-list is intersected with "
                    "the analysis extent, i.e. only tiles included in both the analysis "
                    "extent AND the allow-list will be processed. Default: NULL",
        schema={"type": "array", "items": {"type": "string"}},
        required=False,
    )

    .param(
        name="chunk_size",
        description="This parameter is used to define the size of the sub-tile "
                    "processing units. Most efficient is to use a chunk size that "
                    "coincides with the tile size. Using smaller chunks may be necessary "
                    "if you cannot fit all necessary data into RAM. The tilesize must be "
                    "dividable by the chunk size without remainder. Note that setting "
                    "the chunk size to 0 as was done with the deprecated BLOCK_SIZE "
                    "parameter is not permitted anymore.",
        schema={"type": "array", "items": {"type": "integer"}},
        required=False
    )
    .param(
        name="resolution",
        description="Analysis resolution in metres. The tile (and chunk) size must be dividable by this "
                    "resolution without remainder, e.g. 30m resolution with 100km tiles is not possible."
                    "Default: 20",
        schema={"type": "integer"},
        required=False
    )
    .param(
        name="reduce_psf",
        description="How to reduce spatial resolution for cases when the image resolution is higher "
                    "than the analysis resolution. If FALSE, the resolution is degraded using "
                    "Nearest Neighbor resampling (fast). If TRUE, an approx. Point Spread Function "
                    "(Gaussian lowpass with FWHM = analysis resolution) is used to approximate the "
                    "acquisition of data at lower spatial resolution",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="use_l2_improphe",
        description="If you have spatially enhanced some Level 2 ARD using the FORCE Level 2 "
                    "ImproPhe module, this switch specifies whether the data are used at "
                    "original (False) or enhanced spatial resolution (True). If there are "
                    "no improphe'd products, this switch doesn't have any effect. Default: False",
        schema={"type": "boolean"},
        required=False
    )

    .param(
        name="sensors",
        description="Sensors to be used in the analysis. Multi-sensor analyses are restricted to "
                    "the overlapping bands. Each sensor needs a sensor definition in the runtime-data "
                    "directory. New sensors can be added by the user. New bandnames can be added, too."
                    "Default: SEN2A, SEN2B, SEN2C",
        schema={"type": "string", "enum": ["SEN2A", "SEN2B", "SEN2C"]},
        required=False
    )
    .param(
        name="target_sensors",
        description="Target sensor that represents the combination of input sensors. A sensor "
                    "definition for this target sensor needs to exist to make sure that "
                    "processing those outputs will be possible. For example, if you combine "
                    "Landsat 8 and Sentinel-2, the target sensor containing the overlapping "
                    "bands could be LNDLG. If only using Sentinel-2 sensors, the target "
                    "sensor could be SEN2L. Valid values are the same as for SENSORS. "
                    "Default: SEN2L",
        schema={"type": "string", "enum": ["SEN2A", "SEN2B", "SEN2C", "SEN2L"]},
        required=False
    )
    .param(
        name="product_type_main",
        description="Main product type to be used. Usually, this is a reflectance product "
                    "like BOA. When using composites, you may use BAP. This can be anything, "
                    "but make sure that the string can uniquely identify your product. As "
                    "an example, do not use LEVEL2. Note that the product should contain "
                    "the bands that are to be expected with the sensor used, e.g. 10 bands "
                    "when sensor is SEN2A. Type: Character. Valid values: "
                    "{BOA,TOA,IMP,BAP,SIG,...}. Default: BOA",
        schema={"type": "string"},
        required=False
    )
    .param(
        name="product_type_quality",
        description="Quality product type to be used. This should be a bit flag product "
                    "like QAI. When using composites, you may use INF. This can be "
                    "anything, but make sure that the product should contain quality "
                    "bit flags as outputted by FORCE L2PS. As an exception, it is "
                    "also possible to give NULL if you don't have any quality masks. "
                    "In this case, FORCE will only be able to filter nodata values, "
                    "but no other quality flags as defined with SCREEN_QAI. Valid "
                    "values: {QAI,INF,NULL,...}. Default: QAI",
        schema={"type": "string"},
        required=False
    )
    .param(
        name="spectral_adjust",
        description="Perform a spectral adjustment to Sentinel-2? This method can "
                    "only be used with following sensors: SEN2A, SEN2B, SEN2C, "
                    "SEN2D,LND04, LND05, LND07,  LND08, LND09, MOD01, MOD02. A "
                    "material-specific spectral harmonization will be performed, "
                    "which will convert the  spectral response of any of these "
                    "sensors to Sentinel-2A. Non-existent bands will be  predicted, "
                    "too. Default: False",
        schema={"type": "boolean"},
        required=False
    )

    .param(
        name="screen_qai",
        description="Type: Character list. Valid values: {NODATA,CLOUD_OPAQUE,"
                    "CLOUD_BUFFER,CLOUD_CIRRUS,CLOUD_SHADOW,SNOW,WATER,AOD_FILL,"
                    "AOD_HIGH,AOD_INT,SUBZERO, SATURATION,SUN_LOW,ILLUMIN_NONE,"
                    "ILLUMIN_POOR,ILLUMIN_LOW,SLOPED,WVP_NONE}. Default: "
                    "NODATA CLOUD_OPAQUE CLOUD_BUFFER CLOUD_CIRRUS CLOUD_SHADOW "
                    "SNOW SUBZERO SATURATION",
        schema={"type": "array", "items": {"type": "string"}},
        required=False
    )
    .param(
        name="above_noise",
        description="Threshold for removing outliers. Triplets of observations are "
                    "used to determine the overall noise in the time series by computing "
                    "linearly interpolating between the bracketing observations. The "
                    "RMSE of the residual between the middle value and the interpolation "
                    "is the overall noise. Any observations, which have a residual larger "
                    "than a multiple of the noise are iteratively filtered out (ABOVE_NOISE). "
                    "Lower/Higher values filter more aggressively/conservatively. Likewise, "
                    "any masked out observation (as determined by the SCREEN_QAI filter) can "
                    "be restored if its residual is lower than a multiple of the noise "
                    "(BELOW_NOISE). Higher/Lower values will restore observations more aggressively"
                    "/conservative. Give 0 to both parameters to disable the filtering. "
                    "ABOVE_NOISE = 3, BELOW_NOISE = 1 are parameters that have worked in some "
                    "settings. Default: 0",
        schema={"type": "float"},
        required=False
    )
    .param(
        name="below_noise",
        description="Threshold for removing outliers. Triplets of observations are "
                    "used to determine the overall noise in the time series by computing "
                    "linearly interpolating between the bracketing observations. The "
                    "RMSE of the residual between the middle value and the interpolation "
                    "is the overall noise. Any observations, which have a residual larger "
                    "than a multiple of the noise are iteratively filtered out (ABOVE_NOISE). "
                    "Lower/Higher values filter more aggressively/conservatively. Likewise, "
                    "any masked out observation (as determined by the SCREEN_QAI filter) can "
                    "be restored if its residual is lower than a multiple of the noise "
                    "(BELOW_NOISE). Higher/Lower values will restore observations more aggressively"
                    "/conservative. Give 0 to both parameters to disable the filtering. "
                    "ABOVE_NOISE = 3, BELOW_NOISE = 1 are parameters that have worked in some "
                    "settings. Default: 0",
        schema={"type": "float"},
        required=False
    )

    .param(
        name="index",
        description="Any index defined in indices.json can be used, as well as SMA, or any "
                    "band name present in the SENSORS band combination",
        schema={"type": "array", "items": {"type": "string", "enum": [
            "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B10", "B11", "B12",
            "SMA",
            "NDVI", "EVI", "NBR", "NDTI", "ARVI", "SAVI", "SARVI", "TC-BRIGHT", "TC-GREEN",
            "TC-WET", "TC-DI", "NDBI", "NDWI", "MNDWI", "NDMI", "NDSI", "kNDVI", "NDRE1",
            "NDRE2", "CIre", "NDVIre1", "NDVIre2", "NDVIre3", "NDVIre1n", "NDVIre2n",
            "NDVIre3n", "MSRre", "MSRren", "CCI", "EVI2", "ContRemSWIR"]}},
        required=False,
    )
    .param(
        name="standardize_tss",
        description="Any index defined in indices.json can be used, as well as SMA, or any "
                    "band name present in the SENSORS band combination. Default: NONE",
        schema={"type": "string", "enum": [ "NONE", "NORMALIZE", "CENTER" ]},
        required=False,
    )
    .param(
        name="output_tss",
        description="Output the quality-screened Time Series Stack? This is a layer "
                    "stack of index values for each date. Default: False",
        schema={"type": "boolean"},
        required=False,
    )

    .param(
        name="interpolate",
        description="Interpolation method. You can choose between no, linear, moving average, Radial "
                    "Basis Function or harmonic Interpolation. Harmonic interpolation can be used as "
                    "a simple near-real time monitoring component. sensors can be added by the user. "
                    "New bandnames can be added, too."
                    "Default: NONE",
        schema={"type": "string", "enum": ["NONE", "LINEAR", "MOVING", "RBF", "HARMONIC"]},
        required=False,
    )
    .param(
        name="moving_max",
        description="Max temporal distance for the moving average filter in days. For "
                    "each interpolation date, MOVING_MAX days before and after are considered. "
                    "Default: 16",
        schema={"type": "integer"},
        required=False,
    )
    .param(
        name="rbf_sigma",
        description="Sigma (width of the Gaussian bell) for the RBF filter in days. For each "
                    "interpolation date, a Gaussian kernel is used to smooth the observations. "
                    "The smoothing effect is stronger with larger kernels and the chance of "
                    "having nodata values is lower. Smaller kernels will follow the time series "
                    "more closely but the chance of having nodata values is larger. Multiple "
                    "kernels can be combined to take advantage of both small and large kernel "
                    "sizes. The kernels are weighted according to the data density within each "
                    "kernel. "
                    "Default: 8 16 32",
        schema={"type": "array", "item": {"type": "integer"}},
        required=False,
    )
    .param(
        name="rbf_cutoff",
        description="Cutoff density for the RBF filter. The Gaussian kernels have infinite "
                    "width, which is computationally slow, and doesn't make much sense as "
                    "observations that are way too distant (in terms of time) are considered. "
                    "Thus, the tails of the kernel are cut off. This parameter specifies, "
                    "which percentage of the area under the Gaussian should be used. "
                    "Default: 0.95",
        schema={"type": "float"},
        required=False,
    )
    .param(
        name="harmonic_trend",
        description="Whether a monotonic trend shall be considered in the harmonic interpolation. Default: True",
        schema={"type": "boolean"},
        required=False,
    )
    .param(
        name="harmonic_modes",
        description="Definition of how many modes per season are used for harmonic interpolation, "
                    "i.e. uni-modal (1), bi-modal (2), or tri-modal (3). Default: 3",
        schema={"type": "integer"},
        required=False,
    )
    .param(
        name="harmonic_fit_range",
        description="Subset of the time period to which the harmonic should be fitted."
                    "For example, if the analysis timeframe is DATE_RANGE = 2015-01-01 2022-06-20,"
                    "all data from 2015-2022 will be considered. If HARMONIC_FIT_RANGE = 2015-01-01 2017-12-31,"
                    "the harmonic will only be fitted to the first 3 years of data.",
        schema={"type": "array", "item": { "type": "string" }},
        required=False,
    )
    .param(
        name="output_nrt",
        description="Output of the near-real time product? The product will contain the residual "
                    "between the extrapolated harmonic and the actual data following the defined "
                    "end of the harmonic fit range. This option requires harmonic interpolation "
                    "(interpolate) and a forecast period (harmonic_fit_range).",
        schema={"type": "boolean"},
        required=False,
    )
    .param(
        name="int_days",
        description="This parameter gives the interpolation step in days. Default: 16",
        schema={"type": "integer"},
        required=False,
    )
    .param(
        name="standardize_tsi",
        description="Standardize the TSI time series with pixel mean and/or standard deviation. "
                    "Default: NONE",
        schema={"type": "string", "enum": [ "NONE", "NORMALIZE", "CENTER" ]},
        required=False,
    )
    .param(
        name="output_tsi",
        description="Output the Time Series Interpolation? This is a layer stack of index "
                    "values for each interpolated date. Note that interpolation will be "
                    "performed even if output_tsi = False - unless you specify interpolate = NONE.",
        schema={"type": "boolean"},
        required=False,
    )

    .param(
        name="output_stm",
        description="Whether to output Spectral Temporal Metrics: Default: False",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="stm",
        description="Which Spectral Temporal Metrics should be computed? The STM output files "
                    "will have as many bands as you specify metrics (in the same order). "
                    "Currently available statistics are the average, standard deviation, minimum, "
                    "maximum, range, skewness, kurtosis, any quantile from 1-99%, and "
                    "interquartile range. Note that median is Q50. "
                    "Default: NONE",
        schema={"type": "array", "item": {"type": "string", "enum": [
            "MIN", "Q01", "Q05", "Q10", "Q20", "Q25", "Q30", "Q40", "Q50", "Q60", "Q70", "Q75", "Q80", "Q90", "Q95", "Q99", "MAX", "AVG", "STD", "RNG", "IQR", "SKW", "KRT", "NUM"]}},
        required=False
    )

    .param(
        name="fold_type",
        description="Which statistic should be used for folding the time series? This "
                    "parameter is only evaluated if one of the following outputs in "
                    "this block is requested. Currently available statistics are the "
                    "average, standard deviation, mini- mum, maximum, range, skewness, "
                    "kurtosis, median, 10/25/75/90% quantiles, and interquartile range. "
                    "Default: AVG",
        schema={"type": "array", "item": {"type": "string", "enum": [
            "MIN", "Q10", "Q25", "Q50", "Q75", "Q90", "MAX", "AVG", "STD", "RNG", "IQR", "SKW", "KRT", "NUM"]}},
        required=False
    )
    .param(
        name="standardize_fold",
        description="Standardize the FB* time series with pixel mean and/or standard deviation. Default: NONE",
        schema={"type": "string", "enum": [ "NONE", "NORMALIZE", "CENTER" ]},
        required=False,
    )
    .param(
        name="output_fby",
        description="Output the Fold-by-Year/Quarter/Month/Week/DOY time series? These are layer "
                    "stacks of folded index values for each year, quarter, month, week or DOY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_fbq",
        description="Output the Fold-by-Year/Quarter/Month/Week/DOY time series? These are layer "
                    "stacks of folded index values for each year, quarter, month, week or DOY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_fbm",
        description="Output the Fold-by-Year/Quarter/Month/Week/DOY time series? These are layer "
                    "stacks of folded index values for each year, quarter, month, week or DOY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_fbw",
        description="Output the Fold-by-Year/Quarter/Month/Week/DOY time series? These are layer "
                    "stacks of folded index values for each year, quarter, month, week or DOY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_fbd",
        description="Output the Fold-by-Year/Quarter/Month/Week/DOY time series? These are layer "
                    "stacks of folded index values for each year, quarter, month, week or DOY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_try",
        description="Compute and output a linear trend analysis on any of the folded time "
                    "series? Note that the OUTPUT_FBX parameters don't need to be TRUE to do this.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_trq",
        description="Compute and output a linear trend analysis on any of the folded time "
                    "series? Note that the OUTPUT_FBX parameters don't need to be TRUE to do this.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_trm",
        description="Compute and output a linear trend analysis on any of the folded time "
                    "series? Note that the OUTPUT_FBX parameters don't need to be TRUE to do this.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_trw",
        description="Compute and output a linear trend analysis on any of the folded time "
                    "series? Note that the OUTPUT_FBX parameters don't need to be TRUE to do this.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_trd",
        description="Compute and output a linear trend analysis on any of the folded time "
                    "series? Note that the OUTPUT_FBX parameters don't need to be TRUE to do this.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_cay",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) analysis "
                    "on any of the folded time series? Note that the OUTPUT_FBX parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_caq",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) analysis "
                    "on any of the folded time series? Note that the OUTPUT_FBX parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_cam",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) analysis "
                    "on any of the folded time series? Note that the OUTPUT_FBX parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_caw",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) analysis "
                    "on any of the folded time series? Note that the OUTPUT_FBX parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_cad",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) analysis "
                    "on any of the folded time series? Note that the OUTPUT_FBX parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )

    .param(
        name="pol_start_threshold",
        description="Threshold for detecting a start of season in the cumulative time series."
                    "Default: 0.2",
        schema={"type": "float"},
        required=False
    )
    .param(
        name="pol_mid_threshold",
        description="Threshold for detecting a mid of season in the cumulative time series."
                    "Default: 0.5",
        schema={"type": "float"},
        required=False
    )
    .param(
        name="pol_end_threshold",
        description="Threshold for detecting an end of season in the cumulative time series."
                    "Default: 0.8",
        schema={"type": "float"},
        required=False
    )
    .param(
        name="pol_adaptive",
        description="Should the start of each phenological year be adapated? If FALSE, "
                    "the start is static, i.e. Date of Early Minimum and Date of Late "
                    "Minimum are the same for all years and 365 days apart. If TRUE, "
                    "they differ from year to year and a phenological year is not "
                    "forced to be 365 days long.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="pol",
        description="Which Polarmetrics should be computed? There will be a POL output file "
                    "for each metric (with years as bands). Currently available are the dates "
                    "of the early minimum, late minimum, peak of season, start of season, mid "
                    "of season, end of season, early average vector, average vector, late "
                    "average vector; lengths of the total season, green season, between average "
                    "vectors; values of the early minimum, late minimum, peak of season, start "
                    "of season, mid of season, end of season, early average vector, average "
                    "vector, late average vector, base level, green amplitude, seasonal amplitude, "
                    "peak amplitude, green season mean , green season variability, dates of start "
                    "of phenological year, difference between start of phenological year and its "
                    "longterm average; integrals of the total season, base level, base+total, "
                    "green season, rising rate, falling rate; rates of average rising, average "
                    "falling, maximum rising, maximum falling.",
        schema={"type": "array", "item": {"type": "string", "enum": [
            "DEM", "DLM", "DPS", "DSS", "DMS", "DES", "DEV", "DAV", "DLV", "LTS", "LGS", "LGV",
            "VEM", "VLM", "VPS", "VSS", "VMS", "VES", "VEV", "VAV", "VLV", "VBL", "VGA", "VSA",
            "VPA", "VGM", "VGV", "DPY", "DPV", "IST", "IBL", "IBT", "IGS", "IRR", "IFR", "RAR",
            "RAF", "RMR", "RMF"]}},
        required=False,
    )
    .param(
        name="standardize_pol",
        description="Standardize the POL time series with pixel mean and/or standard deviation.",
        schema={"type": "string", "enum": [ "NONE", "NORMALIZE", "CENTER" ]},
        required=False
    )
    .param(
        name="output_pct",
        description="Output the polar-transformed time series? These are layer stack "
                    "of cartesian X- and Y-coordinates for each interpolated date. "
                    "This results in two files, product IDs are PCX and PCY.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_pol",
        description="Output the Polarmetrics? These are layer stacks per polarmetric with "
                    "as many bands as years.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_tro",
        description="Compute and output a linear trend analysis on the requested "
                    "Polarmetric time series? Note that the OUTPUT_POL parameters "
                    "don't need to be TRUE to do this. See also the TREND PARAMETERS "
                    "block below",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_cao",
        description="Compute and output an extended Change, Aftereffect, Trend (CAT) "
                    "analysis on the requested Polarmetric time series? Note that the "
                    "OUTPUT_POL parameters don't need to be TRUE to do this. See also "
                    "the TREND PARAMETERS block below.",
        schema={"type": "boolean"},
        required=False
    )

    .param(
        name="trend_tail",
        description="This parameter specifies the tail-type used for significance testing of "
                    "the slope in the trend analysis. A left-, two-, or right-tailed t-test "
                    "is performed.",
        schema={"type": "string", "enum": ["LEFT", "TWO", "RIGHT"]},
        required=False
    )
    .param(
        name="trend_conf",
        description="Confidence level for significance testing of the slope in the trend analysis. "
                    "Default: 0.95",
        schema={"type": "float"},
        required=False
    )
    .param(
        name="change_penalty",
        description="In the Change, Aftereffect, Trend (CAT) analysis: do you want to put "
                    "a penalty on non-permanent change for the change detection? This can "
                    "help to reduce the effect of outliers.",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="output_format",
        description="Output format, which is either uncompressed flat binary image "
                    "format aka ENVI Standard, GeoTiff, or COG. GeoTiff images are "
                    "compressed with ZSTD and horizontal differencing; BigTiff support "
                    "is enabled; the Tiff is internally tiled with 256x256 px blocks. "
                    "Metadata are written to the ENVI header or directly into the Tiff "
                    "to the FORCE domain. If the size of the metadata exceeds the Tiff's "
                    "limit, an external .aux.xml file is additionally generated. Note "
                    "that COG output is only possible when the chunk size matches the "
                    "tile size. Default: GTiff",
        schema={"type": "string", "enum": ["GTiff", "COG"]},
        required=False
    )
    .param(
        name="output_explode",
        description="controls whether the output is written as multi-band image, or "
                    "whether the stack will be exploded into single-band files. Default: False",
        schema={"type": "boolean"},
        required=False
    )
    .param(
        name="fail_if_empty",
        description="Controls whether FORCE raises a warning or an error if no read "
                    "or written bytes are detected. The default (False) will result "
                    "in a warning. Default: False",
        schema={"type": "boolean"},
        required=False
    )
    .returns(
        description="the data as a FORCE higher level data cube",
        schema={"type": "object", "subtype": "datacube"}
    )
)
def force_tsa(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/bcdev/apex-force-openeo/refs/heads/main/material/force-tsa.cwl"
        ),
    )


@non_standard_process(
    ProcessSpec(
        id="run_cwl_to_stac",
        description="Proof-of-concept process. Runs CWL and tries to keep all the stac metadata as is.",
    )
    .param(
        name="cwl_url",
        description="cwl_url",
        schema={
            "type": "string",
            "format": "uri",
            "subtype": "uri",
            "pattern": "^https?://",
        },
        required=False,
    )
    .param(
        name="cwl",
        description="Either source code, an absolute URL or a path to a UDF/CWL script.",
        schema=[
            {
                "description": "Absolute URL to a UDF/CWL",
                "type": "string",
                "format": "uri",
                "subtype": "uri",
                "pattern": "^https?://",
            },
            {
                "description": "Path to a UDF/CWL uploaded to the server.",
                "type": "string",
                "subtype": "file-path",
                "pattern": "^[^\r\n\\:'\"]+$",
            },
            {
                "description": "The multi-line source code of a UDF/CWL, must contain a newline/line-break.",
                "type": "string",
                "subtype": "udf-code",
                "pattern": "(\r\n|\r|\n)",
            },
        ],
        required=False,
    )
    .param(
        name="context",
        description="context",
        schema={"type": "dict"},
        required=False,
    )
    .param(
        name="stac_root",
        description="stac_root",
        schema={"type": "string"},
        required=False,
    )
    .param(name="direct_s3_mode", description="direct_s3_mode", schema={"type": "boolean"}, required=False)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def run_cwl_to_stac(args: ProcessArgs, env: EvalEnv) -> StacSaveResult:
    cwl = args.get_optional("cwl_url", expected_type=str)
    if not cwl:
        cwl = args.get_required("cwl", expected_type=str)
    context = args.get_optional("context", expected_type=dict, default={})
    stac_root = args.get_optional("stac_root", expected_type=str, default="collection.json")
    direct_s3_mode = args.get_optional("direct_s3_mode", default=False)
    stac_root_new = cwl_common_to_stac(
        context, env, CwLSource.from_any(cwl), stac_root=stac_root, direct_s3_mode=direct_s3_mode
    )
    return StacSaveResult(stac_root_new)


SAR_BACKSCATTER_COEFFICIENT_DEFAULT = "sigma0-ellipsoid"


def _update_sar_backscatter_spec(spec: dict) -> dict:
    spec = deepcopy(spec)
    spec["experimental"] = False
    spec["description"] += textwrap.dedent(
        """
        \n\n
        ## Backend notes
        The implementation in this backend is based on Orfeo Toolbox.
        """
    )

    (coefficient_param,) = (p for p in spec["parameters"] if p["name"] == "coefficient")

    coefficient_param["description"] = textwrap.dedent(
        f"""\
        The radiometric correction coefficient.
        On this backend, only the following option is available:

        * `{SAR_BACKSCATTER_COEFFICIENT_DEFAULT}`: ground area computed with ellipsoid earth model
        """
    )
    coefficient_param["default"] = SAR_BACKSCATTER_COEFFICIENT_DEFAULT
    coefficient_param["schema"] = {"type": "string", "enum": [SAR_BACKSCATTER_COEFFICIENT_DEFAULT]}

    spec["links"].append(
        {
            "rel": "about",
            "href": "https://www.orfeo-toolbox.org/CookBook/Applications/app_SARCalibration.html",
            "title": "Orfeo toolbox backscatter processor.",
        }
    )

    return spec


@process_registry_100.add_function(
    spec=_update_sar_backscatter_spec(read_spec("openeo-processes/1.x/proposals/sar_backscatter.json")),
    allow_override=True,
)
@process_registry_2xx.add_function(
    spec=_update_sar_backscatter_spec(read_spec("openeo-processes/2.x/proposals/sar_backscatter.json")),
    allow_override=True,
)
def sar_backscatter(args: ProcessArgs, env: EvalEnv):
    cube: DriverDataCube = args.get_required("data", expected_type=DriverDataCube)
    kwargs = args.get_subset(
        names=[
            "coefficient",
            "elevation_model",
            "mask",
            "contributing_area",
            "local_incidence_angle",
            "ellipsoid_incidence_angle",
            "noise_removal",
            "options",
        ]
    )
    kwargs.setdefault("coefficient", SAR_BACKSCATTER_COEFFICIENT_DEFAULT)
    return cube.sar_backscatter(SarBackscatterArgs(**kwargs))
