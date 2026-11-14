from __future__ import annotations

import unittest
from pathlib import Path

from tests.infra.run_browser_acceptance import browser_container_args, browser_host


class BrowserRunnerConfigurationTests(unittest.TestCase):
    def test_macos_uses_docker_desktop_host_alias(self) -> None:
        self.assertEqual(browser_host("Darwin"), "host.docker.internal")
        args = browser_container_args(Path("/tmp/runtime.json"), Path("/tmp/state.json"), "runner", "Darwin")
        self.assertNotIn("--network", args)
        self.assertIn("PALIMPSEST_TEST_HOST=host.docker.internal", args)

    def test_linux_uses_host_network_and_loopback(self) -> None:
        self.assertEqual(browser_host("Linux"), "127.0.0.1")
        args = browser_container_args(Path("/tmp/runtime.json"), Path("/tmp/state.json"), "runner", "Linux")
        self.assertIn("--network", args)
        self.assertEqual(args[args.index("--network") + 1], "host")
        self.assertIn("PALIMPSEST_TEST_HOST=127.0.0.1", args)
        self.assertNotIn("--add-host", args)

    def test_both_modes_keep_runtime_manifest_read_only(self) -> None:
        for system in ("Darwin", "Linux"):
            with self.subTest(system=system):
                args = browser_container_args(Path("/runtime.json"), Path("/state.json"), "runner", system)
                manifest_mount = args[args.index("-v") + 1]
                self.assertEqual(manifest_mount, "/runtime.json:/test-data/runtime.json:ro")


if __name__ == "__main__":
    unittest.main()
