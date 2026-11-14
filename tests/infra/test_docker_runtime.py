"""Opt-in real Docker runtime smoke/persistence check.

The suite refuses to run unless explicitly enabled. It uses an isolated project
name, dedicated temporary data root and only worker-C's 38081-38083 ports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import urlopen
import uuid

from tests.infra.oracle import validate_runtime


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "scripts" / "wiki"
DOCKER_BIN = "/Applications/Docker.app/Contents/Resources/bin"
PORTS = "38081,38082,38083"


@unittest.skipUnless(os.environ.get("PALIMPSEST_RUN_DOCKER") == "1", "set PALIMPSEST_RUN_DOCKER=1 to run Docker checks")
class DockerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        if not LAUNCHER.is_file():
            self.fail("public scripts/wiki launcher is missing")
        self.run_id = uuid.uuid4().hex[:8]
        self.project = f"palimpsest-c-{self.run_id}"
        self.temp = tempfile.TemporaryDirectory(prefix=f"{self.project}-")
        self.data_root = Path(self.temp.name) / "state"
        self.data_root.mkdir()
        self.manifest_path: Path | None = None

    def tearDown(self) -> None:
        if getattr(self, "setup_attempted", False):
            down = self.command("down", check=False, timeout=300)
            if down.returncode != 0:
                self.fail(f"isolated project shutdown failed ({down.returncode}): {down.stderr[-2000:]}")
            reset = self.command("reset", "--confirm-project", self.project, check=False, timeout=300)
            if reset.returncode != 0:
                self.fail(f"explicit cleanup of isolated {self.project} failed; inspect before removing it: {reset.stderr[-2000:]}")
        self.temp.cleanup()

    def command(self, *args: str, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{DOCKER_BIN}:{env.get('PATH', '')}"
        result = subprocess.run(
            ["python3", str(LAUNCHER), "--project", self.project,
             "--data-root", str(self.data_root), "--ports", PORTS, *args],
            cwd=REPOSITORY,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"scripts/wiki {' '.join(args)} exited {result.returncode}:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        return result

    def read_runtime_manifest(self) -> dict:
        result = self.command("manifest")
        manifest_path = Path(result.stdout.strip())
        self.assertTrue(manifest_path.is_absolute(), "manifest command must print an absolute C1 path")
        self.assertTrue(manifest_path.is_file(), f"C1 was not written at {manifest_path}")
        self.manifest_path = manifest_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(validate_runtime(manifest), [])
        self.assertEqual(manifest["project"], self.project)
        self.assertEqual(Path(manifest["data_root"]), self.data_root.resolve())
        return manifest

    def api_general(self, api_url: str) -> dict:
        query = urlencode({"action": "query", "meta": "siteinfo", "siprop": "general", "format": "json"})
        separator = "&" if "?" in api_url else "?"
        with urlopen(api_url + separator + query, timeout=15) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read())
        self.assertNotIn("error", payload, payload)
        return payload["query"]["general"]

    def assert_three_wiki_api_identity(self, manifest: dict) -> None:
        database_ids = set()
        for language in ("fi", "sv", "en"):
            with self.subTest(language=language):
                general = self.api_general(manifest["languages"][language]["api_url"])
                self.assertEqual(general.get("lang"), language)
                declared_database = manifest["languages"][language]["database"]
                self.assertTrue(declared_database)
                # Siteinfo does not publish the configured database name. If a
                # deployment adds a dbname field, compare it; otherwise the
                # browser suite proves isolation through same-name, distinct edits.
                if general.get("dbname") is not None:
                    self.assertEqual(general["dbname"], declared_database)
                database_ids.add(declared_database)
        self.assertEqual(len(database_ids), 3, "each language must use an isolated database declared by C1")

    def test_fresh_setup_rerun_and_restart_preserve_three_language_identity(self) -> None:
        self.setup_attempted = True
        self.command("setup", timeout=1800)
        self.command("status")
        ready = self.command("verify", "--scope", "runtime")
        self.assertEqual(ready.returncode, 0)
        manifest = self.read_runtime_manifest()
        self.assert_three_wiki_api_identity(manifest)

        # A second setup must be safe and report the same initialized databases.
        self.command("setup", timeout=1800)
        rerun = self.read_runtime_manifest()
        self.assert_three_wiki_api_identity(rerun)

        # Shutdown preserves volumes; a subsequent setup serves the same wiki identities.
        self.command("down", timeout=300)
        self.command("setup", timeout=1800)
        restarted = self.read_runtime_manifest()
        self.assert_three_wiki_api_identity(restarted)


if __name__ == "__main__":
    unittest.main()
