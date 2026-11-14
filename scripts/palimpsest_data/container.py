from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .io import DataError

DOCKER_BUNDLE = Path("/Applications/Docker.app/Contents/Resources/bin")


def docker_path() -> Path:
    found = shutil.which("docker")
    if found:
        return Path(found)
    candidate = DOCKER_BUNDLE / "docker"
    if candidate.exists():
        return candidate
    raise DataError("Docker CLI was not found; install/use Docker Desktop or set PATH")


def run_parquet_worker(repo_root: Path, assets: Path, output: Path,
                       *, runner=subprocess.run) -> dict[str, str]:
    docker = docker_path()
    output.mkdir(parents=True, exist_ok=True)
    tag = "palimpsest-data-tooling:s-2026-10"
    env = os.environ.copy()
    env["PATH"] = str(DOCKER_BUNDLE) + os.pathsep + env.get("PATH", "")
    build = [str(docker), "build", "-f", "infra/data/tooling/Dockerfile", "-t", tag, "."]
    built = runner(build, cwd=repo_root, env=env, text=True, capture_output=True, check=False)
    if built.returncode:
        raise DataError(f"failed to build pinned Parquet tooling image: {built.stderr[-2000:]}")
    command = [str(docker), "run", "--rm", "-v", f"{assets.resolve()}:/data:ro", "-v", f"{output.resolve()}:/out", tag,
               "--assets", "/data", "--lock", "/opt/palimpsest/datasets.lock.json", "--output", "/out"]
    ran = runner(command, cwd=repo_root, env=env, text=True, capture_output=True, check=False)
    if ran.returncode:
        raise DataError(f"Parquet membership validation failed in tooling container: {ran.stderr[-2000:]}")
    return {"stdout": ran.stdout, "image": tag}
