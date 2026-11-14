"""Unit coverage for Linux-safe runtime provisioning; never contacts Docker."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("palimpsest_runtime_linux", ROOT / "scripts/runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runtime)


class LinuxRuntimeProvisioningTests(unittest.TestCase):
    def test_database_sql_is_stdin_to_healthy_database_not_an_init_bind_mount(self) -> None:
        values = {f"DB_{lang.upper()}_PASSWORD": f"{lang}-password" for lang in runtime.LANGS}
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(runtime, "run", side_effect=fake_run):
            runtime.apply_init_sql(["docker", "compose"], {"PATH": ""}, "palimpsest-fixture", values)

        command, kwargs = calls[0]
        self.assertEqual(command[-6:], ["exec", "-T", "db", "sh", "-c", 'mariadb -uroot -p"$(cat /run/secrets/db-root-password)"'])
        self.assertIn("CREATE DATABASE IF NOT EXISTS `mw_palimpsest-fixture_fi`", kwargs["input_text"])
        self.assertIn("CREATE USER IF NOT EXISTS 'mw_palimpsest-fixture_en'@'%'", kwargs["input_text"])
        self.assertIn("GRANT ALL PRIVILEGES", kwargs["input_text"])
        compose = (ROOT / "infra/wiki/compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("/docker-entrypoint-initdb.d", compose)

    def test_linux_config_helper_uses_pinned_installer_service(self) -> None:
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(runtime, "run", side_effect=fake_run):
            runtime.configure_config_with_helper(["docker", "compose"], {"PATH": ""}, "fi")

        command, kwargs = calls[0]
        self.assertEqual(command, [
            "docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "sh", "installer",
            "/usr/local/bin/palimpsest-configure-settings.sh",
        ])
        self.assertEqual(kwargs["timeout"], 120)
        helper = (ROOT / "infra/wiki/runtime/configure-settings.sh").read_text(encoding="utf-8")
        self.assertIn("chown 33:33", helper)
        self.assertIn("chmod 0640", helper)
        self.assertIn("chmod 0751", helper)


if __name__ == "__main__":
    unittest.main()
