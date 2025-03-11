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
    openeogeotrellis.deploy.load_custom_processes(path=ROOT / "custom_processes.py")


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
        "schema": [
            {"type": "string", "enum": ["sigma0-ellipsoid"]},
            {"type": "null", "title": "Non-normalized backscatter"},
        ],
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
