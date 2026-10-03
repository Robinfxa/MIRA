"""Public error descriptions must not depend on Python's HTTP status phrases."""
import sys
from pathlib import Path

import fastapi.openapi.utils as openapi_utils
import pytest
from fastapi.testclient import TestClient

from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app
from mira.entrypoints.http.schemas import ErrorResponse
from tools import export_contracts

ROOT = Path(__file__).resolve().parents[2]
ERROR_DESCRIPTIONS = {
    "400": "Bad Request",
    "404": "Not Found",
    "409": "Conflict",
    "422": "Unprocessable Content",
    "503": "Service Unavailable",
}


@pytest.mark.parametrize("platform_phrase", ["Unprocessable Entity", "Unprocessable Content"])
def test_canonical_contract_check_ignores_platform_422_phrase(monkeypatch, platform_phrase):
    # FastAPI 0.128.2 reads this map, built from HTTPStatus.phrase by http.client.
    # Patch its actual fallback rather than a project function or cached schema.
    monkeypatch.setitem(openapi_utils.http.client.responses, 422, platform_phrase)
    monkeypatch.setattr(sys, "argv", ["export_contracts.py", "--check"])
    export_contracts.main()


def test_router_errors_have_stable_descriptions_and_error_response_schema(monkeypatch):
    for status in ERROR_DESCRIPTIONS:
        monkeypatch.setitem(openapi_utils.http.client.responses, int(status), "Platform wording")
    schema = create_app(Settings(), web_root=ROOT / ".no-web").openapi()
    main_seen = media_seen = False
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            responses = operation["responses"]
            required = {"400", "404", "409", "422"}
            if path == "/api/v1/voice-capabilities" or "/speech/" in path:
                required.add("503")
                media_seen = True
            else:
                main_seen = True
            assert required <= responses.keys(), path
            for status in required:
                response = responses[status]
                assert response["description"] == ERROR_DESCRIPTIONS[status], (path, status)
                assert response["content"]["application/json"]["schema"] == {
                    "$ref": "#/components/schemas/ErrorResponse",
                }, (path, status)
    assert main_seen and media_seen
    assert "HTTPValidationError" not in schema["components"]["schemas"]


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/api/v1/sessions", {"client_instance_id": "synthetic-invalid-id"}),
    ("GET", "/api/v1/sessions/synthetic-invalid-id", None),
    ("POST", "/api/v1/sessions/synthetic-invalid-id/speech/invalid-effect/stream", {}),
])
def test_validation_response_still_matches_public_error_contract(method, path, body):
    settings = Settings(diagnostics={"enabled": False})
    with TestClient(create_app(settings, web_root=ROOT / ".no-web")) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 422
    data = response.json()
    assert set(data) == {"code", "message", "request_id"}
    error = ErrorResponse.model_validate(data)
    assert error.code == "invalid_request"
    assert error.message == "Request does not match the contract."
    assert str(error.request_id) == response.headers["X-Request-ID"]
    assert "synthetic-invalid-id" not in response.text
