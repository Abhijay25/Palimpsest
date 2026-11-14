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
        stderr = result.stderr
        if len(stderr) > 10_000:
            stderr = f"{stderr[:5_000]}\n... stderr middle omitted ...\n{stderr[-5_000:]}"
        raise RuntimeError(f"command exited {result.returncode}: {' '.join(args)}\n{result.stdout}\n{stderr}")
    return result


def browser_host(system: str | None = None) -> str:
    """Return the host address reachable from the browser container/network."""
    system = system or platform.system()
    if system == "Linux":
        return "127.0.0.1"
    if system == "Darwin":
        return "host.docker.internal"
    raise RuntimeError(f"browser acceptance runner supports macOS and Linux, not {system}")


def configure_browser_host(data_root: Path, manifest: dict, host: str) -> None:
    """Give this disposable runtime a canonical host reachable from the browser container."""
    for language, entry in manifest["languages"].items():
        port = entry["api_url"].rsplit(":", 1)[-1].split("/", 1)[0]
        if not port.isdigit():
            raise RuntimeError(f"C1 API URL has no explicit port for {language}")
        runtime_settings = data_root / "config" / language / "runtime-settings.php"
        text = runtime_settings.read_text(encoding="utf-8")
        text += f"\n// Browser harness host override for this disposable run.\n$wgServer = 'http://{host}:{port}';\n$wgCanonicalServer = $wgServer;\n"
        runtime_settings.write_text(text, encoding="utf-8")


def browser_container_args(
    manifest: Path,
    browser_state: Path,
    image: str,
    system: str | None = None,
) -> list[str]:
    """Build isolated browser args for Docker Desktop or native Linux Docker."""
    system = system or platform.system()
    host = browser_host(system)
    args = ["docker", "run", "--rm"]
    if system == "Linux":
        # The runtime publishes its ports on the host's loopback interface;
        # host networking lets the browser reach those exact ports.
        args.extend(["--network", "host"])
    # On macOS Docker Desktop provides the host alias; on Linux this is loopback.
    test_host = host
    args.extend([
        "-e", f"PALIMPSEST_TEST_HOST={test_host}",
        "-e", "PALIMPSEST_C1_MANIFEST=/test-data/runtime.json",
        "-v", f"{manifest}:/test-data/runtime.json:ro",
        "-v", f"{browser_state}:/test-data/browser-state.json:rw",
        image,
    ])
    return args


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
    system = platform.system()
    test_host = browser_host(system)
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
        configure_browser_host(data_root, json.loads(manifest.read_text(encoding="utf-8")), test_host)
        # The temporary LocalSettings include is copied at container startup.
        # Restart only this fresh project so generated canonical URLs use the
        # gateway address accessible to the browser container.
        run([*common, "down"], env=env, timeout=300)
        run([*common, "up"], env=env, timeout=300)
        run(["docker", "build", "--pull", "-t", image, "-f", "tests/infra/browser/Dockerfile", "tests/infra/browser"], env=env, timeout=1800)
        image_built = True
        base_run = browser_container_args(manifest, browser_state, image, system)
        run(base_run, env=env, timeout=1800)
        state = json.loads(browser_state.read_text(encoding="utf-8"))
        if {record.get("language") for record in state} != {"fi", "sv", "en"}:
            raise RuntimeError("browser suite did not produce isolated persistence evidence for fi, sv and en")
        run([*common, "down"], env=env, timeout=300)
        run([*common, "setup"], env=env, timeout=1800)
        configure_browser_host(data_root, json.loads(manifest.read_text(encoding="utf-8")), test_host)
        run([*common, "down"], env=env, timeout=300)
        run([*common, "up"], env=env, timeout=300)
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
