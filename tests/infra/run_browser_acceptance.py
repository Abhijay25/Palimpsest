"""Build the pinned browser runner and exercise the disposable C runtime."""

from __future__ import annotations

import os
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "wiki"
DOCKER_BIN = "/Applications/Docker.app/Contents/Resources/bin"
PORTS = "38081,38082,38083"


def run(args: list[str], *, env: dict[str, str], timeout: int, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"command exited {result.returncode}: {' '.join(args)}\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return result


def main() -> int:
    run_id = uuid.uuid4().hex[:8]
    project = f"palimpsest-c-{run_id}"
    image = f"palimpsest-infra-browser:1.65.1-{run_id}"
    env = os.environ.copy()
    env["PATH"] = f"{DOCKER_BIN}:{env.get('PATH', '')}"
    data_temp = tempfile.TemporaryDirectory(prefix=f"{project}-")
    data_root = Path(data_temp.name) / "state"
    data_root.mkdir()
    browser_state = Path(data_temp.name) / "browser-state.json"
    browser_state.write_text("[]", encoding="utf-8")
    common = [
        "python3", str(LAUNCHER), "--project", project,
        "--data-root", str(data_root), "--ports", PORTS,
    ]
    setup_attempted = False
    image_built = False
    try:
        setup_attempted = True
        run([*common, "setup"], env=env, timeout=1800)
        manifest_result = run([*common, "manifest"], env=env, timeout=120)
        manifest = Path(manifest_result.stdout.strip())
        if not manifest.is_absolute() or not manifest.is_file():
            raise RuntimeError("runtime manifest command did not return an absolute C1 file path")
        run(["docker", "build", "--pull", "-t", image, "-f", "tests/infra/browser/Dockerfile", "tests/infra/browser"], env=env, timeout=1800)
        image_built = True
        base_run = ["docker", "run", "--rm"]
        # Docker Desktop supplies host.docker.internal on macOS. Native Linux
        # Docker needs the gateway alias for the same container-to-host route.
        if platform.system() != "Darwin":
            base_run.extend(["--add-host", "host.docker.internal:host-gateway"])
        base_run.extend([
            "-e", "PALIMPSEST_C1_MANIFEST=/test-data/runtime.json",
            "-v", f"{manifest}:/test-data/runtime.json:ro",
            "-v", f"{browser_state}:/test-data/browser-state.json:rw",
            image,
        ])
        run(base_run, env=env, timeout=1800)
        state = json.loads(browser_state.read_text(encoding="utf-8"))
        if {record.get("language") for record in state} != {"fi", "sv", "en"}:
            raise RuntimeError("browser suite did not produce isolated persistence evidence for fi, sv and en")
        run([*common, "down"], env=env, timeout=300)
        run([*common, "setup"], env=env, timeout=1800)
        run([*base_run, "--verify-state", "/test-data/browser-state.json"], env=env, timeout=1800)
    finally:
        if setup_attempted:
            # This names only the disposable project created above. Down preserves
            # volumes; reset removes only this run after its browser evidence exists.
            run([*common, "down"], env=env, timeout=300)
            run([*common, "reset", "--confirm-project", project], env=env, timeout=300)
        if image_built:
            run(["docker", "image", "rm", image], env=env, timeout=300)
        data_temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
