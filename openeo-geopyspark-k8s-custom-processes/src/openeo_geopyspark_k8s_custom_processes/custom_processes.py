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
    cwl_arguments = []
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
    cwl_arguments = []
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
            """This process computes the Interferometric Coherence for a series of Sentinel-1 bursts, allowing to specify custom sizes of the multi-look by setting the coherence_window_ax and coherence_window_rg parameters. It requires you to provide the temporal_extent for the period of interest, the temporal_baseline (6, 12 or more days), the burst_id and sub_swath to select the Sentinel-1 burst of interest.
        The implementation is based on SNAP and defined as a CWL (Common Workflow Language) available here: https://github.com/cloudinsar/s1-workflows/blob/main/cwl/sar_coherence_parallel_temporal_extent.cwl
        https://www.eurac.edu/en/projects/cloudinsar."""
        ),
    )
    .param(
        name="temporal_extent",
        description="temporal_extent",
        schema={"type": "array", "items": {"type": "string"}},
        required=True,
    )
    .param(name="temporal_baseline", description="temporal_baseline", schema={"type": "integer"}, required=True)
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="coherence_window_az", description="coherence_window_az", schema={"type": "integer"}, required=False)
    .param(name="coherence_window_rg", description="coherence_window_rg", schema={"type": "integer"}, required=False)
    .param(name="polarization", description="polarization", schema={"type": "string"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
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
        description="Proof-of-concept process. More info here: https://github.com/bcdev/apex-force-openeo",
    ).returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def force_level2(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(
            "https://raw.githubusercontent.com/bcdev/apex-force-openeo/refs/heads/main/material/force-l2.cwl"
        ),
    )


def is_url_whitelisted(cwl_url: str) -> bool:
    return (
        cwl_url.startswith("https://raw.githubusercontent.com/cloudinsar/")
        or cwl_url.startswith("https://raw.githubusercontent.com/Open-EO/")
        or cwl_url.startswith("https://raw.githubusercontent.com/bcdev/apex-force-openeo/")
        or cwl_url.startswith("https://raw.githubusercontent.com/EmileSonneveld/")
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
        required=True,
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
    cwl_url = args.get_required("cwl_url", expected_type=str)
    context = args.get_optional("context", expected_type=dict, default={})
    stac_root = args.get_optional("stac_root", expected_type=str, default="collection.json")
    direct_s3_mode = args.get_optional("direct_s3_mode", default=False)
    if is_url_whitelisted(cwl_url):
        stac_root_new = cwl_common_to_stac(
            context, env, CwLSource.from_url(cwl_url), stac_root=stac_root, direct_s3_mode=direct_s3_mode
        )
        return StacSaveResult(stac_root_new)
    else:
        raise ValueError("CWL not whitelisted: " + str(cwl_url))


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
