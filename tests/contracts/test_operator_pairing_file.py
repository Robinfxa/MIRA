"""Only synthetic launch codes are generated in these filesystem tests."""
import stat

import pytest

from tools.operator_pairing_file import PairingFileError, create_pairing_material

CODE = "synthetic_pairing_code_for_test_" + "A" * 32


def test_explicit_synthetic_file_is_private_new_and_repr_safe(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    first = create_pairing_material(directory, checkout_root=tmp_path / "repo", code_factory=lambda: CODE)
    assert first.path.read_text() == CODE + "\n"
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o600
    assert CODE not in repr(first)
    second = create_pairing_material(directory, checkout_root=tmp_path / "repo", code_factory=lambda: CODE)
    assert first.path != second.path and first.path.read_text() == CODE + "\n"


@pytest.mark.parametrize("kind", ["checkout", "public", "symlink", "missing"])
def test_invalid_pairing_target_has_no_write_or_generation(tmp_path, kind):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private
    root = tmp_path / "repo"
    if kind == "checkout":
        root = tmp_path
    elif kind == "public":
        private.chmod(0o755)
    elif kind == "symlink":
        path = tmp_path / "alias"
        path.symlink_to(private)
    else:
        path = tmp_path / "missing"
    def should_not_generate():
        pytest.fail("generated a code before validating target")
    with pytest.raises(PairingFileError):
        create_pairing_material(path, checkout_root=root, code_factory=should_not_generate)
    assert list(private.iterdir()) == []


def test_invalid_synthetic_code_is_not_written_or_reflected(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    with pytest.raises(PairingFileError, match="operator_pairing_code_invalid") as failure:
        create_pairing_material(private, checkout_root=tmp_path / "repo",
                                code_factory=lambda: "short-private-marker")
    assert "short-private-marker" not in str(failure.value)
    assert list(private.iterdir()) == []
