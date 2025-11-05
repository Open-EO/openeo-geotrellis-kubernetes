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
from openeo_driver.dry_run import DryRunDataTracer
from openeo_driver.processes import ProcessArgs
from openeo_driver.ProcessGraphDeserializer import (
    ENV_DRY_RUN_TRACER,
    ProcessSpec,
    non_standard_process,
    process_registry_2xx,
    process_registry_100,
)
from openeo_driver.specs import read_spec
from openeo_driver.utils import EvalEnv
import openeogeotrellis.integrations.stac
from openeogeotrellis.integrations.calrissian import CalrissianJobLauncher, CwLSource
from openeogeotrellis.util.runtime import get_job_id, get_request_id
import openeogeotrellis.load_stac

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
        output_paths=["output.txt"],
    )

    for k, v in results.items():
        log.info(f"_cwl_demo_hello result {k!r} at pre-signed URL {v.generate_presigned_url()}")

    return results["output.txt"].read(encoding="utf8")


def cwl_common(
    cwl_arguments: Union[List[str], dict],
    env: EvalEnv,
    cwl_source: CwLSource,
    stac_root: str = "collection.json",
    direct_s3_mode=False,
) -> DriverDataCube:
    dry_run_tracer: DryRunDataTracer = env.get(ENV_DRY_RUN_TRACER)
    if dry_run_tracer:
        # TODO: use something else than `dry_run_tracer.load_stac`
        #       to avoid risk on conflict with "regular" load_stac code flows?
        return dry_run_tracer.load_stac(url="dummy", arguments={})

    _ensure_kubernetes_config()

    log.info(f"Loading CWL from {cwl_source=}")

    launcher = CalrissianJobLauncher.from_context(env)
    results = launcher.run_cwl_workflow(
        cwl_source=cwl_source,
        cwl_arguments=cwl_arguments,
        output_paths=[stac_root],
        env_vars={
            "AWS_ACCESS_KEY_ID": os.environ.get("SWIFT_ACCESS_KEY_ID", os.environ.get("AWS_ACCESS_KEY_ID")),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("SWIFT_SECRET_ACCESS_KEY", os.environ.get("AWS_SECRET_ACCESS_KEY")),
        },
    )

    # TODO: provide generic helper to log some info about the results
    for k, v in results.items():
        log.info(f"result {k!r}: {v.generate_public_url()=} {v.generate_presigned_url()=}")

    if direct_s3_mode:
        collection_url = results["collection.json"].s3_uri()
        load_stac_kwargs = {"stac_io": openeogeotrellis.integrations.stac.S3StacIO()}
    else:
        collection_url = results[stac_root].generate_public_url()
        load_stac_kwargs = {}
    env = env.push(
        {
            # TODO: this is apparently necessary to set explicitly, but shouldn't this be the default?
            "pyramid_levels": "highest",
        }
    )
    return openeogeotrellis.load_stac.load_stac(
        url=collection_url,
        load_params=LoadParameters(),
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

    dry_run_tracer: DryRunDataTracer = env.get(ENV_DRY_RUN_TRACER)
    if dry_run_tracer:
        # TODO: use something else than `dry_run_tracer.load_stac`
        #       to avoid risk on conflict with "regular" load_stac code flows?
        return dry_run_tracer.load_stac(url="dummy", arguments={})

    _ensure_kubernetes_config()

    cwl_source = CwLSource.from_path(CWL_ROOT / "dummy_stac.cwl")
    cwl_arguments = []
    direct_s3_mode = args.get_optional("direct_s3_mode", default=False)
    return cwl_common(cwl_arguments, env, cwl_source, stac_root="collection.json", direct_s3_mode=direct_s3_mode)


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
        stac_root="collection.json",
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
        id="insar_coherence",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
    .param(
        name="InSAR_pairs",
        description="InSAR_pairs",
        schema={
            "type": "array",
            "subtype": "temporal-intervals",
            "minItems": 1,
            "items": {
                "type": "array",
                "subtype": "temporal-interval",
                "uniqueItems": True,
                "minItems": 2,
                "maxItems": 2,
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
        },
        required=True,
    )
    .param(name="polarization", description="polarization", schema={"type": "string"}, required=False)
    .param(name="coherence_window_rg", description="coherence_window_rg", schema={"type": "integer"}, required=True)
    .param(name="coherence_window_az", description="coherence_window_az", schema={"type": "integer"}, required=True)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def insar_coherence(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    kwargs = dict(
        burst_id=args.get_required("burst_id", expected_type=int),
        sub_swath=args.get_required("sub_swath", expected_type=str),
        InSAR_pairs=args.get_required("InSAR_pairs", expected_type=list),
        polarization=args.get_optional("polarization", default="vv", expected_type=str),
        coherence_window_rg=args.get_optional("coherence_window_rg", default=10, expected_type=int),
        coherence_window_az=args.get_optional("coherence_window_az", default=2, expected_type=int),
    )
    return insar_common(
        kwargs, env, "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/insar_coherence.cwl"
    )


@non_standard_process(
    ProcessSpec(
        id="insar_interferogram_snaphu",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
    .param(
        name="InSAR_pairs",
        description="InSAR_pairs",
        schema={
            "type": "array",
            "subtype": "temporal-intervals",
            "minItems": 1,
            "items": {
                "type": "array",
                "subtype": "temporal-interval",
                "uniqueItems": True,
                "minItems": 2,
                "maxItems": 2,
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
        },
        required=True,
    )
    .param(name="polarization", description="polarization", schema={"type": "string"}, required=False)
    .param(name="coherence_window_rg", description="coherence_window_rg", schema={"type": "integer"}, required=True)
    .param(name="coherence_window_az", description="coherence_window_az", schema={"type": "integer"}, required=True)
    .param(name="n_rg_looks", description="n_rg_looks", schema={"type": "integer"}, required=True)
    .param(name="n_az_looks", description="n_az_looks", schema={"type": "integer"}, required=True)
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def insar_interferogram_snaphu(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    kwargs = dict(
        burst_id=args.get_required("burst_id", expected_type=int),
        sub_swath=args.get_required("sub_swath", expected_type=str),
        InSAR_pairs=args.get_required("InSAR_pairs", expected_type=list),
        polarization=args.get_optional("polarization", default="vv", expected_type=str),
        coherence_window_rg=args.get_optional("coherence_window_rg", default=10, expected_type=int),
        coherence_window_az=args.get_optional("coherence_window_az", default=2, expected_type=int),
        n_rg_looks=args.get_optional("n_rg_looks", default=4, expected_type=int),
        n_az_looks=args.get_optional("n_az_looks", default=1, expected_type=int),
    )
    return insar_common(
        kwargs,
        env,
        "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/insar_interferogram_snaphu.cwl",
        stac_root="phase_coh_collection.json",
    )


@non_standard_process(
    ProcessSpec(
        id="insar_preprocessing",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    )
    .param(name="burst_id", description="burst_id", schema={"type": "integer"}, required=True)
    .param(name="sub_swath", description="sub_swath", schema={"type": "string"}, required=True)
    .param(
        name="temporal_extent",
        description="temporal_extent",
        schema={
            "type": "array",
            "subtype": "temporal-interval",
            "uniqueItems": True,
            "minItems": 2,
            "maxItems": 2,
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
    .param(
        name="master_date",
        description="master_date",
        schema={"type": "string", "subtype": "date"},
        required=True,
    )
    .param(
        name="polarization",
        description="polarization",
        schema={"type": ["string", "array"], "items": {"type": "string"}},
        required=False,
    )
    .returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def insar_preprocessing(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    kwargs = dict(
        burst_id=args.get_required("burst_id", expected_type=int),
        sub_swath=args.get_required("sub_swath", expected_type=str),
        temporal_extent=args.get_required("temporal_extent", expected_type=list),
        master_date=args.get_required("master_date", expected_type=str),
        polarization=args.get_optional("polarization", default="vv", expected_type=(str, list)),
    )
    return insar_common(
        kwargs,
        env,
        "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/main/cwl/insar_preprocessing.cwl",
    )


@non_standard_process(
    ProcessSpec(
        id="sar_coherence",
        description="Proof-of-concept process to run CWL based inSAR. More info here: https://github.com/cloudinsar/s1-workflows",
    ).returns(description="the data as a data cube", schema={"type": "object", "subtype": "datacube"})
)
def sar_coherence(args: ProcessArgs, env: EvalEnv) -> DriverDataCube:
    return cwl_common(
        args,
        env,
        CwLSource.from_url(  # TODO: refer to main branch once merged.
            "https://raw.githubusercontent.com/cloudinsar/s1-workflows/refs/heads/renaming/cwl/sar_coherence.cwl"
        ),
        stac_root="S1_2images_collection.json",
    )


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
