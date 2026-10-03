"""FND02-002/003/009: malformed fixture data must fail before any candidate is exposed."""
import json

import pytest

from mira.adapters.generation.replay.script import ReplayScriptError, load_script, parse_script

VALID = {"schema_version": "1", "steps": [{"fixture_id": "photo", "delay_ms": 0}], "finish": "complete"}


def test_valid_script_is_immutable():
    script = parse_script(json.dumps(VALID).encode())
    with pytest.raises(ValueError):
        script.finish = "fail"
    with pytest.raises(ValueError):
        script.steps[0].delay_ms = 1


@pytest.mark.parametrize("patch", [
    {"schema_version": "2"}, {"steps": []}, {"extra": "do-not-reflect"},
    {"steps": [{"fixture_id": "unregistered"}]},
    {"steps": [{"fixture_id": "photo", "value": "do-not-reflect"}]},
    {"steps": [{"fixture_id": "photo", "delay_ms": -1}]},
    {"steps": [{"fixture_id": "photo", "delay_ms": 5001}]},
    {"steps": [{"fixture_id": "photo", "delay_ms": True}]},
    {"steps": [{"fixture_id": "photo", "delay_ms": "1"}]},
    {"steps": [{"fixture_id": "photo", "delay_ms": 5000}] * 3},
    {"steps": [{"fixture_id": "photo"}] * 9}, {"finish": "unknown"},
])
def test_invalid_structure_is_rejected_without_reflecting_payload(patch):
    with pytest.raises(ReplayScriptError) as error:
        parse_script(json.dumps(VALID | patch).encode())
    assert "do-not-reflect" not in str(error.value)


@pytest.mark.parametrize("raw", [b"", b"not-json", b"{", b"\xff", b"[]", b"null", b" " * 16385])
def test_malformed_or_oversized_bytes_fail(raw):
    with pytest.raises(ReplayScriptError):
        parse_script(raw)


def test_missing_terminal_outcome_is_not_inferred_as_success():
    with pytest.raises(ReplayScriptError):
        parse_script(json.dumps({key: value for key, value in VALID.items() if key != "finish"}).encode())


@pytest.mark.parametrize("name", ["../../.env", "/etc/passwd", "https://example.test/script", "unknown"])
def test_only_named_packaged_scenarios_can_be_loaded(name):
    with pytest.raises(ReplayScriptError, match="^unknown_replay_scenario$"):
        load_script(name)


def test_duplicate_json_keys_cannot_replace_failure_with_success():
    raw = b'{"schema_version":"1","steps":[{"fixture_id":"photo"}],"finish":"fail","finish":"complete"}'
    with pytest.raises(ReplayScriptError, match="^invalid_replay_script$"):
        parse_script(raw)


def test_duplicate_nested_keys_cannot_replace_fixture_identity():
    raw = b'{"schema_version":"1","steps":[{"fixture_id":"unregistered","fixture_id":"photo"}],"finish":"complete"}'
    with pytest.raises(ReplayScriptError, match="^invalid_replay_script$"):
        parse_script(raw)
