from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import codex_setup_diagnose as diagnose


MAC_X64 = "5acdb61ada4233af340719ddb243d5e71ea24f04afeed922644d8f1d486d4c79"
MAC_ARM64 = "16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704"
SYNTHETIC_SIZE = 28


def _file(path: Path, *, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"offline synthetic executable")
    path.chmod(mode)
    return path


def _native_package(root: Path, *, arch: str = "x64") -> Path:
    if arch == "x64":
        package, triple = "codex-darwin-x64", "x86_64-apple-darwin"
    else:
        package, triple = "codex-darwin-arm64", "aarch64-apple-darwin"
    return _file(
        root / "node_modules" / "@openai" / package / "vendor" / triple / "bin" / "codex"
    )


def _fake_stat(kind: int, mode: int, *, uid: int | None = None):
    return SimpleNamespace(
        st_mode=kind | mode,
        st_uid=os.getuid() if uid is None else uid,
        st_gid=os.getgid(),
        st_size=SYNTHETIC_SIZE,
    )


def _fake_path_stats(path: Path, overrides: dict[Path, object] | None = None):
    path = Path(os.path.abspath(path))
    entries: dict[Path, object] = {
        Path("/"): _fake_stat(stat.S_IFDIR, 0o755, uid=0),
    }
    current = Path("/")
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        is_leaf = index == len(parts) - 1
        entries[current] = _fake_stat(
            stat.S_IFREG if is_leaf else stat.S_IFDIR,
            0o755,
            uid=os.getuid(),
        )
    entries.update(overrides or {})
    return entries


def _mock_lstat(entries: dict[Path, object]):
    def fake_lstat(path: Path):
        absolute = Path(os.path.abspath(path))
        if absolute not in entries:
            raise FileNotFoundError(absolute)
        return entries[absolute]
    return fake_lstat


class CodexSetupDiagnosticTests(unittest.TestCase):
    def test_no_arguments_are_inert_and_do_not_infer_any_path(self):
        output_stream = io.StringIO()
        with contextlib.redirect_stdout(output_stream):
            self.assertEqual(diagnose.main([]), 0)
        output = json.loads(output_stream.getvalue())
        self.assertFalse(output["inspected"])
        self.assertFalse(output["process_started"])
        self.assertFalse(output["network_used"])
        self.assertEqual(output["blocking_categories"], [])
        self.assertEqual(output["launch_blocking_categories"], [])
        self.assertIn("no_explicit_paths_supplied", output["informational_categories"])

    def test_explicit_official_npm_wrapper_finds_pinned_native_but_wrapper_blocks_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "node_modules" / "@openai" / "codex"
            wrapper = _file(package / "bin" / "codex.js", mode=0o644)
            native = _native_package(package, arch="x64")
            digest = lambda path, size: MAC_X64 if path == native else None
            with patch.object(diagnose, "_file_digest", side_effect=digest):
                result = diagnose.diagnose(str(wrapper), system="Darwin", machine="AMD64")

        report = result["native"]
        self.assertEqual(result["platform"], "macos-x86_64")
        self.assertFalse(result["process_started"])
        self.assertFalse(result["network_used"])
        self.assertEqual(report["role"], "official_npm_native_candidate")
        self.assertEqual(report["selected_role"], "javascript_wrapper")
        self.assertTrue(report["native_established"])
        self.assertTrue(report["version_established"])
        self.assertFalse(report["selected_path_is_native"])
        self.assertEqual(report["version"], "0.159.2")
        self.assertIn("javascript_wrapper_detected", report["blocking_categories"])
        self.assertTrue(any("Select the recognized native executable" in item
                            for item in result["recommendations"]))
        self.assertNotIn(temp, json.dumps(result))

    def test_wrapper_without_known_native_is_blocked_and_wrapper_is_not_hashed(self):
        with tempfile.TemporaryDirectory() as temp:
            wrapper = _file(
                Path(temp) / "node_modules" / "@openai" / "codex" / "bin" / "codex.js",
                mode=0o644,
            )
            calls: list[Path] = []
            with patch.object(
                diagnose, "_file_digest", side_effect=lambda path, size: calls.append(path)
            ):
                result = diagnose.diagnose(str(wrapper), system="Darwin", machine="x86_64")

        self.assertFalse(result["native"]["native_established"])
        self.assertFalse(result["native"]["version_established"])
        self.assertIn("npm_native_candidate_missing", result["native"]["blocking_categories"])
        self.assertEqual(calls, [])

    def test_official_npm_wrapper_finds_hoisted_native_location(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "node_modules" / "@openai" / "codex"
            wrapper = _file(package / "bin" / "codex.js", mode=0o644)
            native = _file(
                root / "node_modules" / "@openai" / "codex-darwin-x64" / "vendor"
                / "x86_64-apple-darwin" / "bin" / "codex"
            )
            digest = lambda path, size: MAC_X64 if path == native else None
            with patch.object(diagnose, "_file_digest", side_effect=digest):
                result = diagnose.diagnose(str(wrapper), system="Darwin", machine="x86_64")

        self.assertTrue(result["native"]["native_established"])
        self.assertFalse(result["native"]["selected_path_is_native"])
        self.assertEqual(result["native"]["version"], "0.159.2")

    def test_platform_layout_and_hash_must_both_match(self):
        with tempfile.TemporaryDirectory() as temp:
            native = _native_package(Path(temp), arch="arm64")
            with patch.object(diagnose, "_file_digest", return_value=MAC_ARM64):
                result = diagnose.diagnose(str(native), system="Darwin", machine="x86_64")

        report = result["native"]
        self.assertEqual(report["selected_role"], "known_npm_native")
        self.assertFalse(report["native_established"])
        self.assertFalse(report["version_established"])
        self.assertIn("platform_pin_mismatch", report["blocking_categories"])
        self.assertIn("npm_native_layout_platform_mismatch", report["blocking_categories"])

    def test_unknown_hash_and_unknown_platform_do_not_establish_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path = _file(Path(temp) / "native-codex")
            unknown_hash = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                unknown_host = diagnose.diagnose(str(path), system="Darwin", machine="ppc64")

        self.assertIn("official_hash_not_recognized",
                      unknown_hash["native"]["blocking_categories"])
        self.assertFalse(unknown_hash["native"]["version_established"])
        self.assertIn("supported_platform_pin_unavailable",
                      unknown_host["native"]["blocking_categories"])
        self.assertFalse(unknown_host["native"]["version_established"])

    def test_symlinked_executable_is_blocked_and_not_hashed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = _file(root / "real" / "codex")
            linked = root / "codex-link"
            linked.symlink_to(original)
            calls: list[Path] = []
            with patch.object(
                diagnose, "_file_digest", side_effect=lambda path, size: calls.append(path)
            ):
                result = diagnose.diagnose(str(linked), system="Darwin", machine="x86_64")

        report = result["native"]
        self.assertFalse(report["native_established"])
        self.assertIn("symlink_in_executable_path", report["blocking_categories"])
        self.assertIn("selected_executable_symlink", report["blocking_categories"])
        self.assertEqual(calls, [])

    def test_current_uid_0755_binary_and_owner_writable_parents_are_informational(self):
        path = Path("/opt/private-bin/codex")
        entries = _fake_path_stats(path)
        with patch.object(Path, "lstat", _mock_lstat(entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")

        report = result["native"]
        self.assertTrue(report["native_established"])
        self.assertEqual(report["blocking_categories"], [])
        self.assertIn("executable_owner_writable", report["informational_categories"])
        self.assertIn("install_ancestor_owner_writable", report["informational_categories"])
        self.assertEqual(result["recommendations"], [])

    def test_root_owned_0755_binary_is_allowed_by_default_guard(self):
        path = Path("/opt/root-bin/codex")
        entries = _fake_path_stats(path, {
            Path("/opt"): _fake_stat(stat.S_IFDIR, 0o755, uid=0),
            Path("/opt/root-bin"): _fake_stat(stat.S_IFDIR, 0o755, uid=0),
            path: _fake_stat(stat.S_IFREG, 0o755, uid=0),
        })
        with patch.object(Path, "lstat", _mock_lstat(entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")

        self.assertTrue(result["native"]["native_established"])
        self.assertNotIn("executable_foreign_owner", result["native"]["blocking_categories"])
        self.assertNotIn("executable_group_or_world_writable",
                         result["native"]["blocking_categories"])
        self.assertEqual(result["recommendations"], [])

    def test_group_or_world_writable_binary_and_parent_block_and_may_recommend_copy(self):
        path = Path("/opt/writable/codex")
        entries = _fake_path_stats(path, {
            Path("/opt/writable"): _fake_stat(stat.S_IFDIR, 0o775),
            path: _fake_stat(stat.S_IFREG, 0o775),
        })
        with patch.object(Path, "lstat", _mock_lstat(entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")

        report = result["native"]
        self.assertIn("executable_group_or_world_writable", report["blocking_categories"])
        self.assertIn("install_ancestor_group_or_world_writable", report["blocking_categories"])
        self.assertTrue(any("private copy" in item for item in result["recommendations"]))

    def test_foreign_owner_binary_and_parent_are_blockers(self):
        foreign_uid = os.getuid() + 10000
        path = Path("/opt/foreign/codex")
        entries = _fake_path_stats(path, {
            Path("/opt/foreign"): _fake_stat(stat.S_IFDIR, 0o755, uid=foreign_uid),
            path: _fake_stat(stat.S_IFREG, 0o755, uid=foreign_uid),
        })
        with patch.object(Path, "lstat", _mock_lstat(entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")

        report = result["native"]
        self.assertIn("executable_foreign_owner", report["blocking_categories"])
        self.assertIn("install_ancestor_foreign_owner", report["blocking_categories"])

    def test_codex_home_must_be_owned_by_current_user(self):
        foreign_uid = os.getuid() + 10000
        home = Path("/home/foreign/.codex")
        entries = _fake_path_stats(home, {
            home: _fake_stat(stat.S_IFDIR, 0o700, uid=foreign_uid),
        })
        with patch.object(Path, "lstat", _mock_lstat(entries)):
            result = diagnose.diagnose(None, str(home))

        self.assertIn("directory_foreign_owner", result["codex_home"]["blocking_categories"])

    def test_setuid_and_setgid_binary_bits_are_blockers(self):
        for special_mode in (0o4755, 0o2755):
            with self.subTest(mode=oct(special_mode)):
                path = Path("/opt/special/codex")
                entries = _fake_path_stats(path, {
                    path: _fake_stat(stat.S_IFREG, special_mode),
                })
                with patch.object(Path, "lstat", _mock_lstat(entries)):
                    with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                        result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")
                self.assertIn("executable_setuid_or_setgid",
                              result["native"]["blocking_categories"])

    def test_root_sticky_tmp_is_allowed_but_unsticky_world_writable_parent_blocks(self):
        path = Path("/tmp/diagnostic/bin/codex")
        safe_entries = _fake_path_stats(path, {
            Path("/tmp"): _fake_stat(stat.S_IFDIR, 0o1777, uid=0),
        })
        with patch.object(Path, "lstat", _mock_lstat(safe_entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                allowed = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")
        self.assertNotIn("install_ancestor_group_or_world_writable",
                         allowed["native"]["blocking_categories"])
        self.assertIn("root_sticky_system_temp_exception",
                      allowed["native"]["informational_categories"])
        self.assertEqual(allowed["recommendations"], [])

        unsafe_entries = _fake_path_stats(path, {
            Path("/tmp"): _fake_stat(stat.S_IFDIR, 0o777, uid=0),
        })
        with patch.object(Path, "lstat", _mock_lstat(unsafe_entries)):
            with patch.object(diagnose, "_file_digest", return_value=MAC_X64):
                blocked = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")
        self.assertIn("install_ancestor_group_or_world_writable",
                      blocked["native"]["blocking_categories"])

    def test_dirs_are_stat_only_and_runtime_emptiness_is_reported_unchecked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home, cwd = root / "home", root / "runtime"
            home.mkdir(mode=0o700)
            cwd.mkdir(mode=0o700)
            with patch.object(Path, "iterdir", side_effect=AssertionError("must not enumerate")):
                result = diagnose.diagnose(None, str(home), str(cwd))

        self.assertFalse(result["codex_home"]["contents_inspected"])
        self.assertFalse(result["runtime_cwd"]["contents_inspected"])
        self.assertFalse(result["runtime_cwd"]["emptiness_checked"])
        self.assertIn("runtime_cwd_emptiness_not_checked",
                      result["runtime_cwd"]["informational_categories"])
        self.assertIn("executable_not_selected", result["native"]["informational_categories"])

    def test_default_home_mode_is_context_dependent_and_paths_are_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir(mode=0o755)
            home.chmod(0o755)
            result = diagnose.diagnose(None, str(home))

        report = result["codex_home"]
        self.assertIn("directory_not_private", report["blocking_categories"])
        self.assertIn(
            "codex_home_development_context_not_inspected",
            report["informational_categories"],
        )
        self.assertNotIn(str(home), json.dumps(result))

    def test_group_writable_codex_home_is_unconditionally_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            home.mkdir(mode=0o775)
            home.chmod(0o775)
            result = diagnose.diagnose(None, str(home))

        report = result["codex_home"]
        self.assertIn("directory_not_private", report["blocking_categories"])
        self.assertIn("directory_group_or_world_writable", report["blocking_categories"])
        self.assertNotIn("directory_not_private", report["conditional_categories"])

    def test_missing_paths_and_symlinked_home_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "not-created"
            real_home = root / "real-home"
            real_home.mkdir(mode=0o700)
            link = root / "home-link"
            link.symlink_to(real_home, target_is_directory=True)
            missing_result = diagnose.diagnose(str(missing), None, str(missing))
            link_result = diagnose.diagnose(None, str(link))

        self.assertIn("executable_missing", missing_result["native"]["blocking_categories"])
        self.assertIn("directory_missing", missing_result["runtime_cwd"]["blocking_categories"])
        self.assertIn("symlink_in_path", link_result["codex_home"]["blocking_categories"])

    def test_relative_paths_do_not_match_public_canonical_path_check(self):
        result = diagnose.diagnose("relative/path/codex", system="Darwin", machine="x86_64")
        self.assertIn(
            "path_not_canonical_absolute", result["native"]["blocking_categories"]
        )
        self.assertIn("executable_missing", result["native"]["blocking_categories"])

    def test_no_environment_or_codex_home_contents_are_reported(self):
        secret = "synthetic-secret-value-not-for-output"
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex-home"
            home.mkdir(mode=0o700)
            (home / "config.toml").write_text(f"api_key = '{secret}'", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": secret}):
                with patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
                    result = diagnose.diagnose(None, str(home))

        self.assertFalse(result["authentication_inspected"])
        self.assertNotIn(secret, json.dumps(result))

    def test_owner_read_search_only_runtime_is_not_reported_launch_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "read-search-runtime"
            runtime.mkdir(mode=0o500)
            report = diagnose.diagnose(None, runtime_cwd=str(runtime))["runtime_cwd"]
        self.assertEqual(report["blocking_categories"], [])
        self.assertEqual(report["launch_blocking_categories"], [])
        self.assertIn("directory_owner_write_unavailable", report["informational_categories"])

    def test_public_home_mode_is_blocked_without_inferred_managed_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex-home"
            home.mkdir(mode=0o755)
            report = diagnose.diagnose(None, codex_home=str(home))["codex_home"]
        self.assertIn("directory_not_private", report["blocking_categories"])
        self.assertNotIn("directory_not_private", report["conditional_categories"])

    def test_directory_without_search_bit_has_specific_launch_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "unsearchable-runtime"
            runtime.mkdir(mode=0o400)
            report = diagnose.diagnose(None, runtime_cwd=str(runtime))["runtime_cwd"]
        self.assertIn("directory_not_user_searchable", report["launch_blocking_categories"])

    def test_all_emitted_diagnostic_categories_have_a_fixed_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            path = _file(Path(temp) / "native-codex")
            result = diagnose.diagnose(str(path), system="Darwin", machine="x86_64")
        for report in (result["native"], result["codex_home"], result["runtime_cwd"]):
            classified = set(
                report["blocking_categories"]
                + report["launch_blocking_categories"]
                + report["conditional_categories"]
                + report["informational_categories"]
            )
            self.assertLessEqual(set(report["categories"]), classified)


if __name__ == "__main__":
    unittest.main()
