import re
from pathlib import Path

import dirty_equals
import flask
import openeo_driver.views
import openeogeotrellis.deploy
import pytest
from openeo_driver.backend import OpenEoBackendImplementation
from openeo_driver.ProcessGraphDeserializer import ConcreteProcessing
from openeo_driver.testing import ApiTester

ROOT = Path(__file__).parent.parent


@pytest.fixture
def backend_implementation() -> OpenEoBackendImplementation:
    return OpenEoBackendImplementation(processing=ConcreteProcessing())


@pytest.fixture
def flask_app(backend_implementation) -> flask.Flask:
    app = openeo_driver.views.build_app(
        backend_implementation=backend_implementation,
        # error_handling=False,
    )
    app.config["TESTING"] = True
    app.config["SERVER_NAME"] = "oeo.net"
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def api(client) -> ApiTester:
    return ApiTester(api_version="1.2", client=client)


@pytest.fixture(scope="session")
def _load_custom_processes():
    # TODO use importlib to get the actual path of the custom_processes. file
    path = ROOT / "src/openeo_geopyspark_k8s_custom_processes/custom_processes.py"
    openeogeotrellis.deploy.load_custom_processes(path=path)


class ProcessListing:
    def __init__(self, raw: dict):
        self.raw = raw

    def get_spec(self, process_id: str) -> dict:
        specs = [p for p in self.raw["processes"] if p["id"] == process_id]
        assert len(specs) == 1
        return specs[0]


@pytest.fixture
def processes_listing(api, _load_custom_processes) -> ProcessListing:
    resp = api.get("/processes").assert_status_code(200).json
    return ProcessListing(raw=resp)


def test_sar_backscatter(processes_listing):
    spec = processes_listing.get_spec(process_id="sar_backscatter")

    (coefficient_param,) = [p for p in spec["parameters"] if p["name"] == "coefficient"]
    assert coefficient_param == {
        "name": "coefficient",
        "description": dirty_equals.IsStr(
            regex=".*only the following option is available:.*sigma0-ellipsoid.*", regex_flags=re.DOTALL
        ),
        "default": "sigma0-ellipsoid",
        "optional": True,
        "schema": {"type": "string", "enum": ["sigma0-ellipsoid"]},
    }

    assert spec == dirty_equals.IsPartialDict(
        {
            "summary": "Computes backscatter from SAR input",
            "experimental": False,
            "description": dirty_equals.IsStr(regex=r".*\n\n## Backend notes.*Orfeo Toolbox.*", regex_flags=re.DOTALL),
            "links": dirty_equals.Contains(
                dirty_equals.IsPartialDict(
                    {
                        "rel": "about",
                        "href": dirty_equals.IsStr(regex=".*orfeo.*"),
                        "title": dirty_equals.IsStr(regex=".*Orfeo.*"),
                    }
                )
            ),
        }
    )


def test_force_level2(processes_listing):
    spec = processes_listing.get_spec(process_id="force_level2")
    parameters = [p["name"] for p in spec["parameters"]]
    assert "name" in parameters
    assert "aoi" in parameters
    assert "resolution" in parameters
    assert "projection" in parameters
    assert "resampling" in parameters
    assert "dem" in parameters
    assert "do_atmo" in parameters
    assert "cloud_buffer" in parameters
    assert "res_merge" in parameters
    assert "output_format" in parameters
    assert all(["name" in p for p in spec["parameters"]])
    assert all(["description" in p for p in spec["parameters"]])
    assert all(["schema" in p for p in spec["parameters"]])
    assert all([p["schema"]["type"] == "boolean" for p in spec["parameters"] if p["name"].startswith("do_")])
    assert all([p["optional"] for p in spec["parameters"] if "Default" in p["description"]])


def _find_raw_urls(text: str) -> list:
    raw_urls = []
    for match in re.finditer(r"https?://\S+", text):
        url = match.group(0).rstrip(".,;:)")
        start, end = match.start(), match.end()
        preceded_by_angle_bracket = start > 0 and text[start - 1] == "<"
        preceded_by_markdown_link = start > 0 and text[start - 1] == "("
        if preceded_by_angle_bracket or preceded_by_markdown_link:
            continue
        raw_urls.append(url)
    return raw_urls


def test_no_raw_urls_in_process_descriptions(processes_listing):
    offenders = {}
    for process in processes_listing.raw["processes"]:
        import logging
        logging.warning(process["id"])
        raw_urls = _find_raw_urls(process.get("description", ""))
        for parameter in process.get("parameters", []):
            raw_urls += _find_raw_urls(parameter.get("description", ""))
        if raw_urls:
            offenders[process["id"]] = raw_urls

    assert offenders == {}


def test_force_tsa(processes_listing):
    spec = processes_listing.get_spec(process_id="force_tsa")
    parameters = [p["name"] for p in spec["parameters"]]
    assert "name" in parameters
    assert "date_range" in parameters
    assert "chunk_size" in parameters
    assert "resolution" in parameters
    assert "sensors" in parameters
    assert "index" in parameters
    assert "standardize_tss" in parameters
    assert "interpolate" in parameters
    assert "int_day" in parameters
    assert "output_stm" in parameters
    assert "stm" in parameters
    assert all(["name" in p for p in spec["parameters"]])
    assert all(["description" in p for p in spec["parameters"]])
    assert all(["schema" in p for p in spec["parameters"]])
    assert all(["NORMALIZE" in p["schema"]["enum"] for p in spec["parameters"] if p["name"].startswith("standardize_")])
    assert all([p["optional"] for p in spec["parameters"] if "Default" in p["description"]])

