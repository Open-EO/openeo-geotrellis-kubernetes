import base64
import json
import logging
import os
import re
from pathlib import Path

import kubernetes.config
from kubernetes.config.incluster_config import SERVICE_TOKEN_FILENAME
from openeo_driver.processes import ProcessArgs
from openeo_driver.ProcessGraphDeserializer import (
    ENV_DRY_RUN_TRACER,
    ProcessSpec,
    non_standard_process,
)
from openeo_driver.utils import EvalEnv
from openeogeotrellis.integrations.calrissian import CalrissianJobLauncher, CwLSource
from openeogeotrellis.util.runtime import get_job_id, get_request_id


log = logging.getLogger("openeo-k8s-custom_processes")
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

    launcher = CalrissianJobLauncher.from_context()
    results = launcher.run_cwl_workflow(
        cwl_source=cwl_source,
        cwl_arguments=cwl_arguments,
        output_paths=["output.txt"],
    )

    return results["output.txt"].read(encoding="utf8")


@non_standard_process(
    ProcessSpec(id="_cwl_demo_insar", description="Proof-of-concept process to run CWL based inSAR.")
    .param(name="spatial_extent", description="Spatial extent.", schema={"type": "dict"}, required=False)
    .param(name="temporal_extent", description="Temporal extent.", schema={"type": "dict"}, required=False)
    .returns(description="the data as a data cube", schema={})
)
def _cwl_demo_insar(args: ProcessArgs, env: EvalEnv):
    """Proof of concept openEO process to run CWL based processing"""
    spatial_extent = args.get_optional("spatial_extent", default=None)
    temporal_extent = args.get_optional("temporal_extent", default=None)

    if env.get(ENV_DRY_RUN_TRACER):
        return "dummy"

    _ensure_kubernetes_config()

    cwl_source = CwLSource.from_path(CWL_ROOT / "insar.cwl")
    input_dict = {
        "spatial_extent": spatial_extent,
        "temporal_extent": temporal_extent,
    }
    input_base64_json = base64.b64encode(json.dumps(input_dict).encode("utf8")).decode("ascii")
    cwl_arguments = ["--input_base64_json", input_base64_json]

    launcher = CalrissianJobLauncher.from_context()
    results = launcher.run_cwl_workflow(
        cwl_source=cwl_source,
        cwl_arguments=cwl_arguments,
        output_paths=["output.txt"],
        env_vars={
            "AWS_ACCESS_KEY_ID": os.environ.get("SWIFT_ACCESS_KEY_ID", ""),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("SWIFT_SECRET_ACCESS_KEY", ""),
        },
    )

    # TODO: Load the results as datacube with load_stac.

    return results["output.txt"].read(encoding="utf8")
