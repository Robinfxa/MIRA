"""Managed-home composition accepts the official Codex default without starting providers."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from mira.adapters.generation.codex_app_server import CodexRuntime
from mira.adapters.generation.codex_support.types import ApprovedDevelopmentContext
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V1
from mira.bootstrap.development_app import create_development_app
from mira.config.loader import ConfigurationError
from mira.config.settings import Settings
from tests.contracts.test_development_review_composition import SyntheticJevTransport


def _managed_runtime(environment, *, codex_home="/synthetic/home/.codex"):
    environment = dict(environment)
    environment_fingerprint = hashlib.sha256(json.dumps(
        environment, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    context = ApprovedDevelopmentContext(
        route_value_sha256=hashlib.sha256(b"synthetic-approved-route").hexdigest(),
        observed_home_mode=0o700,
        managed_environment_sha256=environment_fingerprint,
    )
    return CodexRuntime(
        executable=Path("/synthetic/codex"),
        codex_home=Path(codex_home),
        runtime_cwd=Path("/synthetic/run"),
        environment=environment,
        expected_config_sha256=hashlib.sha256(b"synthetic-config").hexdigest(),
        policy_environment_confirmed=True,
        development_context=context,
    )


def _compose(runtime, *, authorized=True, route_kind="managed",
             decision_policy=USER_DEVELOPMENT_0_6_V1):
    input_jev = SyntheticJevTransport()
    output_jev = SyntheticJevTransport()
    starts = []

    async def codex_factory(*_):
        starts.append("codex")
        raise AssertionError("factory construction must not start a provider transport")

    app = create_development_app(
        runtime=runtime,
        settings=Settings(),
        route_kind=route_kind,
        input_transport=input_jev,
        output_transport=output_jev,
        authorized=authorized,
        decision_policy=decision_policy,
        codex_transport_factory=codex_factory,
    )
    return app, input_jev, output_jev, starts


def test_managed_factory_accepts_official_home_codex_default_without_side_effects():
    environment = {"HOME": "/synthetic/home"}
    runtime = _managed_runtime(environment)

    app, input_jev, output_jev, starts = _compose(runtime)

    assert isinstance(app, FastAPI)
    assert "CODEX_HOME" not in runtime.environment
    assert dict(runtime.environment) == environment
    assert input_jev.calls == output_jev.calls == []
    assert starts == []


@pytest.mark.parametrize(("environment", "codex_home"), [
    ({}, "/synthetic/home/.codex"),
    ({"HOME": "relative/home"}, "/synthetic/home/.codex"),
    ({"HOME": "/synthetic/../home"}, "/synthetic/home/.codex"),
    ({"HOME": "relative/home", "CODEX_HOME": "/synthetic/home/.codex"},
     "/synthetic/home/.codex"),
    ({"HOME": "/synthetic/home", "CODEX_HOME": ""}, "/synthetic/home/.codex"),
    ({"HOME": "/synthetic/home", "CODEX_HOME": "/other/.codex"},
     "/synthetic/home/.codex"),
])
def test_managed_factory_rejects_invalid_home_bindings(environment, codex_home):
    runtime = _managed_runtime(environment, codex_home=codex_home)

    with pytest.raises(ConfigurationError, match="explicit pinned admission"):
        _compose(runtime)


def test_managed_default_does_not_bypass_route_authorization_or_policy_gates():
    runtime = _managed_runtime({"HOME": "/synthetic/home"})

    with pytest.raises(ConfigurationError, match="route kind and pinned runtime context"):
        _compose(runtime, route_kind="public")
    with pytest.raises(ConfigurationError, match="explicit transmission and spend admission"):
        _compose(runtime, authorized=False)
    with pytest.raises(ConfigurationError, match="supported immutable policy"):
        _compose(runtime, decision_policy=object())
