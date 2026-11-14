import importlib.util
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("palimpsest_runtime", ROOT / "scripts/runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runtime)


class RuntimeContractTests(unittest.TestCase):
    def test_c1_has_three_distinct_language_endpoints_and_no_credentials(self):
        lock = runtime.load_lock()
        value = runtime.manifest_value("palimpsest-a", Path("/tmp/runtime"), {"fi": 18081, "sv": 18082, "en": 18083}, lock)
        self.assertEqual(value["schema_version"], 1)
        self.assertEqual(set(value["languages"]), {"fi", "sv", "en"})
        self.assertEqual([value["languages"][lang]["database"] for lang in runtime.LANGS], ["mw_palimpsest-a_fi", "mw_palimpsest-a_sv", "mw_palimpsest-a_en"])
        self.assertEqual([value["ports"][lang] for lang in runtime.LANGS], [18081, 18082, 18083])
        serialized = json.dumps(value).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("token", serialized)

    def test_bad_port_tuple_fails_as_invalid_configuration(self):
        for ports in ("18081,18082", "18081,18081,18083", "0,18082,18083", "abc,2,3"):
            with self.subTest(ports=ports), self.assertRaises(runtime.RuntimeErrorExit) as caught:
                runtime.parse_ports(ports)
            self.assertEqual(caught.exception.status, 2)

    def test_compose_env_file_excludes_all_generated_passwords(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            values = {key: "fixture" for key in runtime.COMPOSE_ENV_KEYS}
            values.update({"DB_ROOT_PASSWORD": "root-secret", "DB_FI_PASSWORD": "fi-secret", "ADMIN_FI_PASSWORD": "admin-secret"})
            runtime.write_env_file(path, values)
            text = path.read_text()
            self.assertNotIn("root-secret", text)
            self.assertNotIn("fi-secret", text)
            self.assertNotIn("admin-secret", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_health_requires_valid_api_json_with_siteinfo(self):
        url = "http://127.0.0.1:18081/api.php"
        valid = BytesIO(json.dumps({"query": {"general": {"sitename": "test", "lang": "fi"}}}).encode())
        with patch.object(runtime.urllib.request, "urlopen", return_value=valid):
            self.assertTrue(runtime.api_healthy(url, expected_language="fi"))
        wrong_language = BytesIO(json.dumps({"query": {"general": {"sitename": "test", "lang": "sv"}}}).encode())
        with patch.object(runtime.urllib.request, "urlopen", return_value=wrong_language):
            self.assertFalse(runtime.api_healthy(url, expected_language="fi"))
        malformed = BytesIO(b"not json")
        with patch.object(runtime.urllib.request, "urlopen", return_value=malformed):
            self.assertFalse(runtime.api_healthy(url))

    def test_installer_generated_extension_calls_are_removed_before_single_runtime_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config/fi"
            config.mkdir(parents=True)
            (config / "LocalSettings.php").write_text("<?php\nwfLoadSkin( 'Vector' );\nwfLoadExtension( 'Cite' );\n$wgDBpassword = 'fixture';\n")
            with patch.object(runtime, "ROOT", Path(__file__).resolve().parents[2]):
                runtime.append_runtime_settings(root, "fi")
            for lang in ("sv", "en"):
                other = root / f"config/{lang}"
                other.mkdir(parents=True)
                (other / "LocalSettings.php").write_text("<?php\n")
                (other / "runtime-settings.php").write_text("<?php\n")
            text = (config / "LocalSettings.php").read_text()
            self.assertEqual(text.count("wfLoadSkin( 'Vector' )"), 0)
            self.assertEqual(text.count("wfLoadExtension( 'Cite' )"), 0)
            self.assertEqual(text.count("require_once '/etc/palimpsest/runtime-settings.php';"), 1)
            self.assertTrue((config / "runtime-settings.php").is_file())
            self.assertEqual((config / "LocalSettings.php").stat().st_mode & 0o777, 0o600)
            (config / "LocalSettings.php").chmod(0o644)
            runtime.secure_configs(root)
            self.assertEqual((config / "LocalSettings.php").stat().st_mode & 0o777, 0o600)

    def test_runtime_reset_preserves_data_tool_files_and_rejects_symlinked_runtime_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared-root"
            (root / "db").mkdir(parents=True)
            (root / "db/state").write_text("runtime")
            (root / "history").mkdir()
            (root / "history/checkpoint.json").write_text("data worker")
            runtime.cleanup_runtime_paths(root)
            self.assertFalse((root / "db").exists())
            self.assertEqual((root / "history/checkpoint.json").read_text(), "data worker")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared-root"
            root.mkdir()
            target = Path(tmp) / "outside"
            target.mkdir()
            (root / "db").symlink_to(target, target_is_directory=True)
            with self.assertRaises(runtime.RuntimeErrorExit):
                runtime.cleanup_runtime_paths(root)
            self.assertTrue(target.is_dir())

    def test_partial_setup_resume_preserves_successful_languages_and_rejects_marker_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fi = root / "config/fi"
            fi.mkdir(parents=True)
            (fi / "LocalSettings.php").write_text("<?php\n")
            (fi / "runtime-settings.php").write_text("<?php\n")
            existing = {"schema_version": 1, "project": "palimpsest-a", "initialized": {"fi": True, "sv": False, "en": False}}
            resumed = runtime.prepare_setup_marker("palimpsest-a", root, existing)
            self.assertEqual(resumed["initialized"], {"fi": True, "sv": False, "en": False})
            self.assertTrue(resumed["initialized"]["fi"])
            self.assertFalse((root / "config/sv/LocalSettings.php").exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sv = root / "config/sv"
            sv.mkdir(parents=True)
            (sv / "LocalSettings.php").write_text("<?php\n")
            existing = {"schema_version": 1, "project": "palimpsest-a", "initialized": {"fi": False, "sv": False, "en": False}}
            with self.assertRaises(runtime.RuntimeErrorExit):
                runtime.prepare_setup_marker("palimpsest-a", root, existing)


if __name__ == "__main__":
    unittest.main()
