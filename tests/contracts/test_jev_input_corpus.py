"""Corpus integrity only; no model-quality claims or provider calls."""
import json
from pathlib import Path


def test_chinese_corpus_is_synthetic_bounded_and_preserves_simultaneous_labels():
    path = Path(__file__).resolve().parents[2] / "specs/features/WP01-semantic-contracts/calibration-corpus.zh.json"
    corpus = json.loads(path.read_text())
    assert corpus["live_execution_authorized"] is False
    assert corpus["evidence_class"] == "offline_synthetic_expected_cases_not_model_quality_evidence"
    cases = corpus["cases"]
    assert 16 <= len(cases) <= 32
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["context"] in corpus["contexts"]
        expected = case["expected"]
        assert set(expected) == {"speech_restriction", "capture_restriction", "display_request", "referent", "status"}
        for key in ("speech_restriction", "capture_restriction", "display_request"):
            assert expected[key] in ("yes", "no", "unknown", None)
        assert expected["referent"] in (None, "none", "ambiguous", *corpus["contexts"][case["context"]]["referents"])
    simultaneous = next(case for case in cases if case["id"] == "two_restrictions_show")
    assert all(simultaneous["expected"][key] == "yes" for key in (
        "speech_restriction", "capture_restriction", "display_request"))
    stop = next(case for case in cases if case["id"] == "local_stop")
    assert stop["local_stop"] and stop["expected"]["status"] == "unavailable"
