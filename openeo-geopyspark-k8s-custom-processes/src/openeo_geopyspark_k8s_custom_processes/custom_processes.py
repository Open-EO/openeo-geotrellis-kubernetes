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
                       '"properties": { "name": "Bologna" }, "id": "08" } . Default: not set, '
                       'extent determined by inputs',
           schema={"type": "string"},
           required=False)
    .param(name="resolution",
           description="Spatial resolution in meters of the FORCE data cube. Example: 10 . Default: 20",
           schema={"type": "integer"},
           required=False)
    .param(name="projection",
           description="Defines the target coordinate system. This projection should ideally be valid for a large "
                       "geographic extent. Two default projection / grid systems are predefined in FORCE. They can "
                       "be specified via the PROJECTION parameter instead of giving a WKT string. The predefined "
                       "options have their own settings for ORIGIN_LAT, ORIGIN_LON, TILE_SIZE, and BLOCK_SIZE, thus "
                       "the values given in the parameterfile will be ignored. EQUI7 consists of 7 Equi-Distant, "
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
           description="Indicates if atmospheric correction shall be performed. If True, Bottom-of-Atmosphere "
                       "reflectance is computed. If False, only Top-of-Atmosphere reflectance is computed. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_topo",
           description="Indicates if topographic correction shall be performed. If True, a DEM need to be named. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_brdf",
           description="Indicates if BRDF correction shall be performed. If True, output is nadir BRDF adjusted "
                       "reflectance instead of BOA reflectance (the output is named BOA nonetheless). "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_adjacency",
           description="Indicates if adjacency effect correction shall be performed. "
                       "Default: True",
           schema={"type": "boolean"},
           required=False)
    .param(name="do_multi_scattering",
           description="Indicates if multiple scattering (True) or the single scattering approximation (False) shall "
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
    .param(naem="res_merge",
           description="Defines the method used for improving the spatial reso lution of Sentinel-2’s 20 m bands "
                       "to 10 m. Pixels flagged as cloud or shadow will be skipped. Following methods are "
                       "available: IMPROPHE uses the ImproPhe code in a spectral-only setup; REGRESSION "
                       "uses a multi- parameter regression (results are expected to be best, but processing "
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
    .param(naem="output_format",
           description="Output format, which is either uncompressed flat binary image format aka ENVI Standard, "
                       "GeoTiff, or COG. GeoTiff images are compressed with LZW and horizontal differencing; "
                       "BigTiff support is enabled; the Tiff is structured with striped blocks according to the "
                       "TILE_SIZE (X) and BLOCK_SIZE (Y) specifications. Metadata are written to the ENVI "
                       "header or directly into the Tiff to the FORCE domain. If the size of the metadata "
                       "exceeds the Tiff's limit, an external .aux.xml file is additionally generated. Valid "
                       "values on CDSE: {GTiff,COG}",
           schema={"type": "string", "enum": ["GTiff", "COG"]},
           required=False)
    .param(name="output_dst",
           description="Indicates whether to output the cloud/cloud shadow/snow distance output? Note that this "
                       "is NOT the cloud mask (which is sitting in the mandatory QAI product). This product can "
                       "be used in force-level3; no other higher-level FORCE module is using this. "
                       "Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_aod",
           description="Indicates whether to output Aerosol Optical Depth map for the green band? No "
                       "higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_wvp",
           description="Indicates whether to output the Water Vapor map? No higher-level FORCE module is using "
                       "this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_vzn",
           description="Indicates whether to output the View Zenith map? This product can be used in force-level3; "
                       "no other higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_hot",
           description="Indicates whether to output the Haze Optimzed Transformation output? This product "
                       "can be used in force-level3; no other higher-level FORCE module is using this. "
                       "Default: False",
           schema={"type": "boolean"},
           required=False)
    .param(name="output_ovv",
           description="Indicates whether to output overview thumbnails? These are jpegs at reduced spatial "
                       "resolution, which feature an RGB overview + quality information overlayed (pink: cloud, "
                       "red: cirrus, cyan: cloud shadow, yellow: snow, orange: saturated, green: subzero "
                       "reflectance). No higher-level FORCE module is using this. Default: False",
           schema={"type": "boolean"},
           required=False)
    .returns(description="the data as a FORCE data cube",
             schema={"type": "object", "subtype": "datacube"},
             required=False)
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
