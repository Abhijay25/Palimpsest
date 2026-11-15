import importlib.util
import json
import subprocess
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

    def test_native_profile_preserves_addons_without_changing_image_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/runtime.MARKER).write_text(json.dumps({'project':'owned'}))
            profile={'schema_version':1,'project':'owned','overrides':['issues','rendering'],'environment':{'PALIMPSEST_ISSUES_SERVICE_URL':'http://private:8766'}}
            path=root/runtime.NATIVE_PROFILE;path.write_text(json.dumps(profile))
            prefix=runtime.compose_prefix('docker',root/'.env')
            self.assertIn(str(runtime.PROFILE_OVERRIDES['issues']),prefix)
            self.assertIn(str(runtime.PROFILE_OVERRIDES['rendering']),prefix)
            self.assertEqual(runtime.native_profile(root)['environment'],profile['environment'])
            profile['environment']['MEDIAWIKI_IMAGE']='unreviewed:latest';path.write_text(json.dumps(profile))
            with self.assertRaises(runtime.RuntimeErrorExit):runtime.native_profile(root)
            profile['environment'].pop('MEDIAWIKI_IMAGE');profile['project']='another';path.write_text(json.dumps(profile))
            with self.assertRaises(runtime.RuntimeErrorExit):runtime.native_profile(root)

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

    def test_import_mount_is_dedicated_and_rejects_symlinks(self):
        compose = (ROOT / "infra/wiki/compose.yaml").read_text()
        self.assertEqual(compose.count("${DATA_ROOT}/imports:/data/imports:ro"), 3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            root.mkdir()
            imports = runtime.prepare_import_mount(root)
            self.assertTrue(imports.is_dir())
            external = Path(tmp) / "external"
            external.mkdir()
            (root / "imports").rmdir()
            (root / "imports").symlink_to(external, target_is_directory=True)
            with self.assertRaises(runtime.RuntimeErrorExit):
                runtime.prepare_import_mount(root)

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
            managed = (config / "runtime-settings.php").read_text()
            self.assertIn("$wgDefaultSkin = 'vector-2022';", managed)
            self.assertIn("https://www.wikipedia.org/", managed)
            self.assertIn("CC BY-SA 4.0", managed)
            self.assertNotIn("wikipedia.org/wiki/", managed)
            self.assertEqual((config / "LocalSettings.php").stat().st_mode & 0o777, 0o600)
            (config / "LocalSettings.php").chmod(0o644)
            runtime.secure_configs(root)
            self.assertEqual((config / "LocalSettings.php").stat().st_mode & 0o777, 0o600)

    def test_first_language_config_does_not_require_uninstalled_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=root/'config/fi'
            first.mkdir(parents=True)
            (first/'LocalSettings.php').write_text('<?php\n')
            with patch.object(runtime,'config_needs_container_helper',return_value=False):
                runtime.configure_runtime_settings(root,'fi',[],{})
            self.assertTrue((first/'runtime-settings.php').is_file())
            # Steady-state validation still requires all three configurations.
            with self.assertRaises(runtime.RuntimeErrorExit):runtime.secure_configs(root)

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

    def test_reset_preserves_runtime_data_when_compose_cannot_stop_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            root.mkdir()
            marker = {"schema_version": 1, "project": "palimpsest-a", "initialized": {"fi": True, "sv": True, "en": True}}
            (root / runtime.MARKER).write_text(json.dumps(marker))
            (root / ".env").write_text("PROJECT=palimpsest-a\n")
            state = root / "db/fixture"
            state.parent.mkdir()
            state.write_text("preserve while containers may still use it")
            args = runtime.parser().parse_args([
                "--project", "palimpsest-a", "--data-root", str(root),
                "reset", "--confirm-project", "palimpsest-a",
            ])
            with patch.object(runtime, "resolve_docker", return_value=("docker", {})), \
                 patch.object(runtime, "docker_preflight"), \
                 patch.object(runtime, "compose_action", return_value=subprocess.CompletedProcess([], 1, "", "container shutdown failed")), \
                 patch.object(runtime, "cleanup_runtime_paths") as cleanup:
                with self.assertRaises(runtime.RuntimeErrorExit) as caught:
                    runtime.runtime_main(args)
            cleanup.assert_not_called()
            self.assertIn("runtime data was preserved", str(caught.exception))
            self.assertIn("container shutdown failed", str(caught.exception))
            self.assertEqual(state.read_text(), "preserve while containers may still use it")

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

    def test_repeat_setup_refreshes_managed_settings_without_rotating_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            marker = {"schema_version": 1, "project": "palimpsest-a", "created_at": "fixture",
                      "initialized": {lang: True for lang in runtime.LANGS}}
            root.mkdir()
            (root / runtime.MARKER).write_text(json.dumps(marker))
            saved = {"DB_ROOT_PASSWORD": "root-pass"}
            saved.update({f"DB_{lang.upper()}_PASSWORD": f"db-{lang}-pass" for lang in runtime.LANGS})
            saved.update({f"ADMIN_{lang.upper()}_PASSWORD": f"admin-{lang}-pass" for lang in runtime.LANGS})
            (root / "secrets").mkdir()
            (root / "secrets/.runtime-env.json").write_text(json.dumps(saved))
            for lang in runtime.LANGS:
                config = root / f"config/{lang}"
                config.mkdir(parents=True)
                (config / "LocalSettings.php").write_text(
                    "<?php\n$wgDBpassword = 'db-credential-preserved';\nwfLoadSkin( 'Vector' );\n"
                    "require_once '/etc/palimpsest/runtime-settings.php';\n"
                )
                (config / "runtime-settings.php").write_text("<?php // stale managed settings\n")

            inventory = {"mediawiki_version": "1.46.2", "extensions": {}, "skins": {"Vector": {"version": "1.0"}}, "integrations": {}}
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                if command[:3] == ["docker", "run", "--rm"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps(inventory), "")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(runtime, "run", side_effect=fake_run), patch.object(runtime, "wait_service"):
                runtime.setup("palimpsest-a", root, {"fi": 18081, "sv": 18082, "en": 18083},
                              runtime.load_lock(), "docker", {})

            self.assertEqual(json.loads((root / "secrets/.runtime-env.json").read_text()), saved)
            configure_calls = [" ".join(command) for command in calls
                               if "/usr/local/bin/palimpsest-configure-interwiki.php" in command]
            self.assertEqual(len(configure_calls), 3)
            for lang in runtime.LANGS:
                settings = (root / f"config/{lang}/LocalSettings.php").read_text()
                managed = (root / f"config/{lang}/runtime-settings.php").read_text()
                self.assertIn("db-credential-preserved", settings)
                self.assertEqual(settings.count("require_once '/etc/palimpsest/runtime-settings.php';"), 1)
                self.assertNotIn("stale managed settings", managed)
                self.assertIn("vector-2022", managed)
                self.assertTrue(any(f"wiki-{lang}" in command for command in configure_calls))


if __name__ == "__main__":
    unittest.main()
