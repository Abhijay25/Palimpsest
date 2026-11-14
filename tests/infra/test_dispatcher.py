from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "scripts" / "wiki"


class DispatcherContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="palimpsest-dispatcher-")
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copy2(LAUNCHER, scripts / "wiki")
        self.capture = self.root / "child-argv.json"
        stub = (
            "import json, os, sys\n"
            "with open(os.environ['CAPTURE_ARGS'], 'w', encoding='utf-8') as stream:\n"
            "    json.dump(sys.argv[1:], stream)\n"
            "raise SystemExit(int(os.environ.get('CHILD_EXIT', '0')))\n"
        )
        (scripts / "runtime.py").write_text(stub, encoding="utf-8")
        (scripts / "data.py").write_text(stub, encoding="utf-8")
        self.launcher = scripts / "wiki"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def invoke(self, *args: str, cwd: Path | None = None, child_exit: int = 0) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CAPTURE_ARGS"] = str(self.capture)
        env["CHILD_EXIT"] = str(child_exit)
        return subprocess.run(
            [sys.executable, str(self.launcher), *args],
            cwd=cwd or self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def child_argv(self) -> list[str]:
        return json.loads(self.capture.read_text(encoding="utf-8"))

    def test_runtime_commands_route_to_runtime_and_preserve_exit_code(self) -> None:
        result = self.invoke("--project", "palimpsest-c", "--ports", "38081,38082,38083", "status", child_exit=7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            self.child_argv(),
            ["--project", "palimpsest-c", "--ports", "38081,38082,38083", "status"],
        )

    def test_verify_runtime_routes_to_status_while_data_scopes_route_to_data(self) -> None:
        runtime = self.invoke("verify", "--scope", "runtime")
        self.assertEqual(runtime.returncode, 0, runtime.stderr)
        self.assertEqual(self.child_argv(), ["status"])

        sample = self.invoke("--project", "palimpsest-c", "verify", "--scope", "sample")
        self.assertEqual(sample.returncode, 0, sample.stderr)
        self.assertEqual(self.child_argv(), ["--project", "palimpsest-c", "verify", "--scope", "sample"])

        full_equals = self.invoke("verify", "--scope=full")
        self.assertEqual(full_equals.returncode, 0, full_equals.stderr)
        self.assertEqual(self.child_argv(), ["verify", "--scope=full"])

    def test_child_help_is_forwarded_and_relative_data_root_is_absolute_from_caller(self) -> None:
        help_result = self.invoke("dataset", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertEqual(self.child_argv(), ["dataset", "--help"])

        caller = self.root / "caller"
        caller.mkdir()
        relative = self.invoke("--data-root", "state/run", "status", cwd=caller)
        self.assertEqual(relative.returncode, 0, relative.stderr)
        self.assertEqual(self.child_argv(), ["--data-root", str((caller / "state/run").resolve()), "status"])

    def test_main_help_needs_no_child_and_invalid_verify_scope_is_rejected(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(self.launcher), "--help"], cwd=self.root, text=True, capture_output=True, check=False
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("Commands:", help_result.stdout)
        self.assertFalse(self.capture.exists())

        actual_help = subprocess.run(
            [sys.executable, str(LAUNCHER), "--help"], cwd=REPOSITORY, text=True, capture_output=True, check=False
        )
        self.assertEqual(actual_help.returncode, 0)
        self.assertIn("Commands:", actual_help.stdout)

        invalid = self.invoke("verify", "--scope", "mystery")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("verify requires --scope", invalid.stderr)
        self.assertFalse(self.capture.exists())

    def test_equals_runtime_scope_is_routed_to_runtime_status(self) -> None:
        result = self.invoke("verify", "--scope=runtime")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.child_argv(), ["status"])


if __name__ == "__main__":
    unittest.main()
