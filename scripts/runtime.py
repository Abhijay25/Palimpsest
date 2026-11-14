#!/usr/bin/env python3
"""Standard-library entry point for the local Palimpsest MediaWiki runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra/wiki/compose.yaml"
LOCK_FILE = ROOT / "infra/wiki/images.lock.json"
EXT_CHECK = ROOT / "infra/wiki/runtime/check_extensions.php"
LANGS = ("fi", "sv", "en")
DEFAULT_PORTS = (8081, 8082, 8083)
MARKER = ".palimpsest-runtime.json"
RUNTIME_OWNED_PATHS = ("db", "init", "config", "uploads", "secrets", ".env", MARKER, "runtime.json")
COMPOSE_ENV_KEYS = {
    "PROJECT", "DATA_ROOT", "MEDIAWIKI_IMAGE", "MARIADB_IMAGE", "PORT_FI", "PORT_SV", "PORT_EN",
    "INSTALL_DB_NAME", "INSTALL_DB_USER", "INSTALL_LANG", "INSTALL_SERVER", "INSTALL_DIR", "INSTALL_SECRET_DIR",
}
EXTENSIONS = (
    "Cite", "ParserFunctions", "Scribunto", "TemplateData", "TemplateStyles",
    "Linter", "Echo", "VisualEditor", "WikiEditor", "DiscussionTools",
)


class RuntimeErrorExit(Exception):
    def __init__(self, message: str, status: int = 1):
        super().__init__(message)
        self.status = status


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage the isolated Palimpsest MediaWiki runtime")
    p.add_argument("--project", default="palimpsest", help="Compose project name (default: palimpsest)")
    p.add_argument("--data-root", default=str(ROOT / ".local/wiki"), help="Directory for this runtime's durable state")
    p.add_argument("--ports", default="8081,8082,8083", help="Host ports for fi,sv,en")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("setup", "up", "down", "status", "logs", "update", "manifest"):
        cmd = sub.add_parser(name)
        if name == "logs":
            cmd.add_argument("--follow", action="store_true")
            cmd.add_argument("--tail", type=int, default=100)
    reset = sub.add_parser("reset", help="Delete only a confirmed project's local runtime state")
    reset.add_argument("--confirm-project", required=True)
    exe = sub.add_parser("exec", help="Run a command in one language wiki container")
    exe.add_argument("--language", choices=LANGS, required=True)
    exe.add_argument("command_args", nargs=argparse.REMAINDER)
    return p


def parse_ports(value: str) -> dict[str, int]:
    try:
        values = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise RuntimeErrorExit("--ports must be three comma-separated integers", 2) from exc
    if len(values) != 3 or any(port < 1 or port > 65535 for port in values) or len(set(values)) != 3:
        raise RuntimeErrorExit("--ports must contain three distinct ports from 1 to 65535", 2)
    return dict(zip(LANGS, values))


def validate_project(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,35}", value):
        raise RuntimeErrorExit("--project must start with a lowercase letter or digit and contain only lowercase letters, digits, '_' or '-' (max 36)", 2)
    return value


def resolve_docker() -> tuple[str, dict[str, str]]:
    env = os.environ.copy()
    docker = shutil.which("docker", path=env.get("PATH"))
    candidates = [
        Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
        Path("/usr/local/bin/docker"), Path("/opt/homebrew/bin/docker"),
    ]
    if not docker:
        docker = next((str(p) for p in candidates if p.is_file()), None)
    if not docker:
        raise RuntimeErrorExit("Docker CLI not found. Install Docker Desktop/Engine with Compose v2.")
    docker_dir = str(Path(docker).resolve().parent)
    env["PATH"] = docker_dir + os.pathsep + env.get("PATH", "")
    return docker, env


def run(args: list[str], *, env: dict[str, str], check: bool = True, capture: bool = False,
        cwd: Path = ROOT, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, timeout=timeout)
    if check and result.returncode:
        raise RuntimeErrorExit(f"Runtime command failed with exit status {result.returncode}. Full command details are omitted to protect local credentials.", result.returncode or 1)
    return result


def shlex(args: list[str]) -> str:
    import shlex as shell_lex
    return shell_lex.join(args)


def load_lock() -> dict[str, Any]:
    try:
        lock = json.loads(LOCK_FILE.read_text())
        for name in ("mediawiki", "mariadb"):
            image = lock["images"][name]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image["digest"]):
                raise ValueError(f"invalid {name} digest")
        if not {"linux/amd64", "linux/arm64"}.issubset(set(lock["platforms"])):
            raise ValueError("image lock must cover linux/amd64 and linux/arm64")
        return lock
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeErrorExit(f"Invalid image lock {LOCK_FILE}: {exc}", 2) from exc


def docker_preflight(env: dict[str, str], docker: str) -> None:
    info = run([docker, "info", "--format", "{{.OSType}}/{{.Architecture}}"], env=env, check=False, capture=True, timeout=20)
    if info.returncode:
        raise RuntimeErrorExit("Docker Engine is unavailable. Start Docker Desktop/Engine, then retry.")
    compose = run([docker, "compose", "version", "--short"], env=env, check=False, capture=True, timeout=20)
    if compose.returncode:
        raise RuntimeErrorExit("Docker Compose v2 is required.")


def make_env(project: str, data_root: Path, ports: dict[str, int], lock: dict[str, Any],
             *, install: dict[str, str] | None = None) -> dict[str, str]:
    mw = lock["images"]["mediawiki"]
    db = lock["images"]["mariadb"]
    values: dict[str, str] = {
        "PROJECT": project, "DATA_ROOT": str(data_root),
        "MEDIAWIKI_IMAGE": f"{mw['reference']}@{mw['digest']}",
        "MARIADB_IMAGE": f"{db['reference']}@{db['digest']}",
        "PORT_FI": str(ports["fi"]), "PORT_SV": str(ports["sv"]), "PORT_EN": str(ports["en"]),
        "DB_ROOT_PASSWORD": "", "DB_FI_NAME": f"mw_{project}_fi", "DB_SV_NAME": f"mw_{project}_sv", "DB_EN_NAME": f"mw_{project}_en",
        "DB_FI_USER": f"mw_{project}_fi", "DB_SV_USER": f"mw_{project}_sv", "DB_EN_USER": f"mw_{project}_en",
        "DB_FI_PASSWORD": "", "DB_SV_PASSWORD": "", "DB_EN_PASSWORD": "",
        "INSTALL_DB_NAME": "", "INSTALL_DB_USER": "", "INSTALL_LANG": "en", "INSTALL_SERVER": "http://127.0.0.1:1",
        "INSTALL_DIR": str(data_root / "config/en"), "INSTALL_SECRET_DIR": str(data_root / "secrets/en"),
    }
    secret_file = data_root / "secrets/.runtime-env.json"
    if secret_file.exists():
        try:
            values.update(json.loads(secret_file.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeErrorExit(f"Cannot read runtime secret state: {exc}") from exc
    if install:
        values.update(install)
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    # JSON double-quoted values follow Compose dotenv escaping and preserve paths with spaces.
    lines = [f"{key}={json.dumps(str(values[key]))}" for key in sorted(COMPOSE_ENV_KEYS) if key in values]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def compose_prefix(docker: str, env_file: Path) -> list[str]:
    return [docker, "compose", "--project-directory", str(ROOT), "-f", str(COMPOSE_FILE), "--env-file", str(env_file)]


def project_marker(data_root: Path) -> dict[str, Any] | None:
    marker = data_root / MARKER
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeErrorExit(f"Runtime state marker is unreadable ({marker}); preserve data and inspect before resetting") from exc


def prepare_setup_marker(project: str, data_root: Path, existing: dict[str, Any] | None) -> dict[str, Any]:
    if existing is None:
        return {"schema_version": 1, "project": project, "created_at": datetime.now(timezone.utc).isoformat(), "initialized": {lang: False for lang in LANGS}}
    if existing.get("project") != project:
        raise RuntimeErrorExit(f"Data root belongs to project '{existing.get('project')}', not '{project}'")
    flags = existing.get("initialized")
    if not isinstance(flags, dict):
        raise RuntimeErrorExit("Runtime marker has no valid per-language initialization state; inspect before retrying.")
    normalized = {}
    for lang in LANGS:
        done = flags.get(lang, False)
        if not isinstance(done, bool):
            raise RuntimeErrorExit(f"Runtime marker has an invalid initialization state for {lang}.")
        settings = data_root / f"config/{lang}/LocalSettings.php"
        runtime_settings = data_root / f"config/{lang}/runtime-settings.php"
        has_config = settings.is_file() or runtime_settings.is_file()
        if done and not (settings.is_file() and runtime_settings.is_file()):
            raise RuntimeErrorExit(f"Runtime marker says {lang} is initialized but its settings files are incomplete.")
        if not done and has_config:
            raise RuntimeErrorExit(f"An unfinished installer left settings files for {lang} without a completion marker; inspect before retrying or resetting.")
        normalized[lang] = done
    return {**existing, "initialized": normalized}


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def cleanup_runtime_paths(root: Path) -> None:
    """Remove only paths owned by this runtime; data-tool state may share the root."""
    for name in RUNTIME_OWNED_PATHS:
        path = root / name
        if path.is_symlink():
            raise RuntimeErrorExit(f"Reset refused: runtime-owned path is a symlink ({path})")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    try:
        root.rmdir()
    except OSError:
        pass


def manifest_value(project: str, data_root: Path, ports: dict[str, int], lock: dict[str, Any]) -> dict[str, Any]:
    marker = project_marker(data_root)
    initialized = (marker or {}).get("initialized", {})
    extension_inventory = (marker or {}).get("extension_inventory")
    if not isinstance(extension_inventory, dict):
        extension_inventory = {name: {"version": None, "status": "not inspected"} for name in EXTENSIONS}
    versions = {
        "mediawiki": {"reference": lock["images"]["mediawiki"]["reference"], "digest": lock["images"]["mediawiki"]["digest"], "resolved_version": (marker or {}).get("mediawiki_version")},
        "mariadb": {"reference": lock["images"]["mariadb"]["reference"], "digest": lock["images"]["mariadb"]["digest"]},
        "extensions": extension_inventory,
        "skins": (marker or {}).get("skin_inventory", {"Vector": {"version": None, "status": "not inspected"}}),
        "integrations": (marker or {}).get("integrations", {"Parsoid": {"status": "not inspected"}}),
    }
    return {
        "schema_version": 1,
        "project": project,
        "data_root": str(data_root),
        "ports": ports,
        "languages": {
            lang: {"api_url": f"http://127.0.0.1:{ports[lang]}/api.php", "service": f"wiki-{lang}", "database": f"mw_{project}_{lang}"}
            for lang in LANGS
        },
        "versions": versions,
        "initialized": {lang: bool(initialized.get(lang, False)) for lang in LANGS},
    }


def api_healthy(url: str, expected_language: str | None = None, timeout: float = 2.0) -> bool:
    query = url + "?action=query&meta=siteinfo&format=json"
    try:
        with urllib.request.urlopen(query, timeout=timeout) as response:
            payload = json.load(response)
        general = payload.get("query", {}).get("general", {})
        return isinstance(general.get("sitename"), str) and (expected_language is None or general.get("lang") == expected_language)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return False


def require_initialized(data_root: Path, project: str) -> dict[str, Any]:
    marker = project_marker(data_root)
    if not marker or marker.get("project") != project:
        raise RuntimeErrorExit(f"No initialized runtime for project '{project}' at {data_root}. Run setup first.")
    if not all(marker.get("initialized", {}).get(lang, False) for lang in LANGS):
        raise RuntimeErrorExit("Runtime marker is incomplete. Inspect setup logs; reset only with explicit confirmation.")
    return marker


def ensure_free_ports(ports: dict[str, int]) -> None:
    for lang, port in ports.items():
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeErrorExit(f"Host port {port} for {lang} is unavailable; select another --ports tuple", 2) from exc


def generate_secrets(project: str, root: Path) -> dict[str, str]:
    import secrets
    secret_dir = root / "secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    saved_path = secret_dir / ".runtime-env.json"
    if saved_path.exists():
        try:
            values = json.loads(saved_path.read_text())
            required = ["DB_ROOT_PASSWORD", *[f"DB_{lang.upper()}_PASSWORD" for lang in LANGS], *[f"ADMIN_{lang.upper()}_PASSWORD" for lang in LANGS]]
            if all(values.get(key) for key in required):
                ensure_secret_files(secret_dir, values)
                return values
        except (OSError, json.JSONDecodeError):
            pass
        raise RuntimeErrorExit("Secret state exists but is incomplete or unreadable; refusing to replace credentials")
    values = {"DB_ROOT_PASSWORD": secrets.token_hex(32)}
    values.update({f"DB_{lang.upper()}_PASSWORD": secrets.token_hex(32) for lang in LANGS})
    values.update({f"ADMIN_{lang.upper()}_PASSWORD": secrets.token_urlsafe(24) for lang in LANGS})
    saved_path.write_text(json.dumps(values, indent=2) + "\n")
    saved_path.chmod(0o600)
    ensure_secret_files(secret_dir, values)
    return values


def ensure_secret_files(secret_dir: Path, values: dict[str, str]) -> None:
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_dir.chmod(0o700)
    root_pw = secret_dir / "db-root-password"
    write_or_check_secret(root_pw, values["DB_ROOT_PASSWORD"])
    for lang in LANGS:
        lang_dir = secret_dir / lang
        lang_dir.mkdir(mode=0o700, exist_ok=True)
        lang_dir.chmod(0o700)
        for filename, key in (("db-password", f"DB_{lang.upper()}_PASSWORD"), ("admin-password", f"ADMIN_{lang.upper()}_PASSWORD")):
            write_or_check_secret(lang_dir / filename, values[key])


def write_or_check_secret(path: Path, value: str) -> None:
    expected = value + "\n"
    if path.exists():
        if path.read_text() != expected:
            raise RuntimeErrorExit(f"Secret file disagrees with saved credential state: {path}; refusing to replace it")
    else:
        path.write_text(expected)
    path.chmod(0o600)


def write_init_sql(root: Path, project: str, values: dict[str, str]) -> None:
    init_dir = root / "init"
    init_dir.mkdir(parents=True, exist_ok=True)
    sql = []
    for lang in LANGS:
        key = lang.upper()
        # All names are validated slugs and passwords are generated hex, so this stays SQL-safe.
        dbname = f"mw_{project}_{lang}"
        user = dbname
        sql.extend([
            f"CREATE DATABASE IF NOT EXISTS `{dbname}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
            f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{values[f'DB_{key}_PASSWORD']}';",
            f"GRANT ALL PRIVILEGES ON `{dbname}`.* TO '{user}'@'%';",
        ])
    path = init_dir / "10-create-wikis.sql"
    path.write_text("\n".join(sql) + "\n")
    path.chmod(0o600)


def append_runtime_settings(root: Path, lang: str) -> None:
    settings = root / f"config/{lang}/LocalSettings.php"
    text = settings.read_text()
    # install may emit the selected bundled skin. Keep extension/skin activation in one file.
    names = set(EXTENSIONS) | {"Vector"}
    quoted = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    text = re.sub(rf"^\s*wfLoad(?:Skin|Extension)\(\s*['\"](?:{quoted})['\"]\s*\);\s*\n", "", text, flags=re.MULTILINE)
    include = "require_once '/etc/palimpsest/runtime-settings.php';"
    if include not in text:
        settings.write_text(text.rstrip() + "\n\n" + include + "\n")
    settings.chmod(0o600)
    runtime_settings = settings.parent / "runtime-settings.php"
    shutil.copyfile(ROOT / "infra/wiki/runtime-settings.php", runtime_settings)
    runtime_settings.chmod(0o644)


def secure_configs(root: Path) -> None:
    for lang in LANGS:
        settings = root / f"config/{lang}/LocalSettings.php"
        runtime_settings = root / f"config/{lang}/runtime-settings.php"
        if not settings.is_file() or not runtime_settings.is_file():
            raise RuntimeErrorExit(f"Project config is missing for {lang}; preserve runtime data and inspect before repairing.")
        settings.chmod(0o600)
        runtime_settings.chmod(0o644)


def setup(project: str, data_root: Path, ports: dict[str, int], lock: dict[str, Any], docker: str, docker_env: dict[str, str]) -> None:
    existing = project_marker(data_root)
    marker = prepare_setup_marker(project, data_root, existing)
    complete = all(marker["initialized"].get(lang, False) for lang in LANGS)
    if not existing:
        ensure_free_ports(ports)
        free = shutil.disk_usage(data_root.parent if data_root.parent.exists() else ROOT).free
        if free < 10 * 1024**3:
            raise RuntimeErrorExit("At least 10 GiB free space is required for the runtime image and database volumes.")
    data_root.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        (data_root / f"config/{lang}").mkdir(parents=True, exist_ok=True)
        (data_root / f"uploads/{lang}").mkdir(parents=True, exist_ok=True)
    values = generate_secrets(project, data_root)
    write_init_sql(data_root, project, values)
    env_values = make_env(project, data_root, ports, lock)
    env_values.update(values)
    env_file = data_root / ".env"
    write_env_file(env_file, env_values)
    prefix = compose_prefix(docker, env_file)
    run(prefix + ["config", "--quiet"], env=docker_env)

    print("Pulling digest-pinned MediaWiki and MariaDB images…", flush=True)
    run(prefix + ["pull", "db"], env=docker_env)
    checked = run([docker, "run", "--rm", "--entrypoint", "php", "-v", f"{EXT_CHECK}:/tmp/check_extensions.php:ro", env_values["MEDIAWIKI_IMAGE"], "/tmp/check_extensions.php"], env=docker_env, capture=True, timeout=120)
    try:
        image_inventory = json.loads(checked.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorExit("Image extension check returned invalid inventory JSON") from exc
    if complete:
        secure_configs(data_root)
        existing["mediawiki_version"] = image_inventory["mediawiki_version"]
        existing["extension_inventory"] = image_inventory["extensions"]
        existing["skin_inventory"] = image_inventory["skins"]
        existing["integrations"] = image_inventory["integrations"]
        write_json_atomic(data_root / MARKER, existing)
        run(prefix + ["up", "-d", "db", "wiki-fi", "wiki-sv", "wiki-en"], env=docker_env)
        for lang in LANGS:
            wait_service(prefix, env_file, f"wiki-{lang}", docker_env, timeout=180)
            run(prefix + ["exec", "-T", f"wiki-{lang}", "php", "maintenance/run.php", "update", "--quick"], env=docker_env, timeout=300)
        run(prefix + ["up", "-d", "jobs-fi", "jobs-sv", "jobs-en"], env=docker_env)
        write_manifest(project, data_root, ports, lock)
        print(f"Runtime for project {project} is already initialized; verified services and refreshed schema state.")
        return
    run(prefix + ["up", "-d", "db"], env=docker_env)
    wait_service(prefix, env_file, "db", docker_env, timeout=180)

    marker["mediawiki_version"] = image_inventory["mediawiki_version"]
    marker["extension_inventory"] = image_inventory["extensions"]
    marker["skin_inventory"] = image_inventory["skins"]
    marker["integrations"] = image_inventory["integrations"]
    write_json_atomic(data_root / MARKER, marker)
    for lang in LANGS:
        if marker["initialized"].get(lang):
            continue
        lang_dir = data_root / f"config/{lang}"
        secret_dir = data_root / f"secrets/{lang}"
        install_values = {
            "INSTALL_DB_NAME": env_values[f"DB_{lang.upper()}_NAME"],
            "INSTALL_DB_USER": env_values[f"DB_{lang.upper()}_USER"],
            "INSTALL_LANG": lang,
            "INSTALL_SERVER": f"http://127.0.0.1:{ports[lang]}",
            "INSTALL_DIR": str(lang_dir),
            "INSTALL_SECRET_DIR": str(secret_dir),
        }
        write_env_file(env_file, make_env(project, data_root, ports, lock, install=install_values) | values)
        install_cmd = prefix + ["run", "--rm", "installer", "php", "maintenance/run.php", "install",
            f"--dbname={install_values['INSTALL_DB_NAME']}", "--dbserver=db", f"--dbuser={install_values['INSTALL_DB_USER']}",
            "--dbpassfile=/run/secrets/install-db-password", f"--server={install_values['INSTALL_SERVER']}",
            f"--lang={lang}", "--passfile=/run/secrets/install-admin-password", "--confpath=/tmp/palimpsest-config",
            "--scriptpath=", f"Palimpsest {lang.upper()}", "admin"]
        run(install_cmd, env=docker_env, timeout=300)
        append_runtime_settings(data_root, lang)
        marker["initialized"][lang] = True
        write_json_atomic(data_root / MARKER, marker)

    run(prefix + ["up", "-d", "wiki-fi", "wiki-sv", "wiki-en"], env=docker_env)
    for lang in LANGS:
        wait_service(prefix, env_file, f"wiki-{lang}", docker_env, timeout=180)
        run(prefix + ["exec", "-T", f"wiki-{lang}", "php", "maintenance/run.php", "update", "--quick"], env=docker_env, timeout=300)
    run(prefix + ["up", "-d", "jobs-fi", "jobs-sv", "jobs-en"], env=docker_env)
    write_manifest(project, data_root, ports, lock)
    print(f"Initialized fi/sv/en wikis for project {project}.")
    print("Admin usernames are 'admin'; per-language passwords are stored in the local secrets directory.")


def wait_service(prefix: list[str], env_file: Path, service: str, env: dict[str, str], timeout: int) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = run(prefix + ["ps", "--format", "json", service], env=env, check=False, capture=True, timeout=15)
        if result.returncode == 0:
            try:
                rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                if any(row.get("Health") == "healthy" for row in rows):
                    return
                if any(row.get("State") == "exited" for row in rows):
                    raise RuntimeErrorExit(f"Service {service} exited before becoming healthy; inspect logs.")
            except json.JSONDecodeError:
                pass
        time.sleep(3)
    raise RuntimeErrorExit(f"Timed out waiting for {service} health check.")


def write_manifest(project: str, root: Path, ports: dict[str, int], lock: dict[str, Any]) -> Path:
    value = manifest_value(project, root, ports, lock)
    out = root / "runtime.json"
    write_json_atomic(out, value)
    return out


def compose_action(prefix: list[str], env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(prefix + list(args), env=env, check=check)


def runtime_main(ns: argparse.Namespace) -> int:
    project = validate_project(ns.project)
    ports = parse_ports(ns.ports)
    root = Path(ns.data_root).expanduser().resolve()
    if root == Path("/") or root == ROOT:
        raise RuntimeErrorExit("--data-root must be a dedicated runtime directory, not a filesystem or repository root", 2)
    lock = load_lock()
    docker, env = resolve_docker()
    env_file = root / ".env"
    prefix = compose_prefix(docker, env_file)
    if ns.command == "manifest":
        marker = project_marker(root)
        if marker and marker.get("project") != project:
            raise RuntimeErrorExit(f"Data root belongs to project '{marker.get('project')}', not '{project}'")
        out = write_manifest(project, root, ports, lock)
        print(out)
        return 0
    if ns.command == "setup":
        docker_preflight(env, docker)
        setup(project, root, ports, lock, docker, env)
        return 0
    if ns.command == "reset":
        if ns.confirm_project != project:
            raise RuntimeErrorExit("Reset refused: --confirm-project must exactly match --project", 2)
        marker = project_marker(root)
        if not marker or marker.get("project") != project:
            raise RuntimeErrorExit("Reset refused: data root has no matching project marker")
        docker_preflight(env, docker)
        if env_file.exists():
            compose_action(prefix, env, "down", "-v", "--remove-orphans", check=False)
        cleanup_runtime_paths(root)
        print(f"Removed runtime-owned state for project {project} at {root}; unrelated data was preserved.")
        return 0
    if ns.command == "down":
        marker = project_marker(root)
        if marker and marker.get("project") != project:
            raise RuntimeErrorExit(f"Data root belongs to project '{marker.get('project')}', not '{project}'")
        if not env_file.exists():
            print(f"No runtime environment file for project {project}; nothing to stop.")
            return 0
        docker_preflight(env, docker)
        return compose_action(prefix, env, "down").returncode
    require_initialized(root, project)
    docker_preflight(env, docker)
    if ns.command == "up":
        compose_action(prefix, env, "up", "-d", "db", "wiki-fi", "wiki-sv", "wiki-en", "jobs-fi", "jobs-sv", "jobs-en")
        for lang in LANGS:
            wait_service(prefix, env_file, f"wiki-{lang}", env, timeout=180)
        return 0
    if ns.command == "logs":
        args = ["logs", "--tail", str(max(0, ns.tail))]
        if ns.follow:
            args.append("--follow")
        return compose_action(prefix, env, *args).returncode
    if ns.command == "exec":
        cmd = ns.command_args[1:] if ns.command_args[:1] == ["--"] else ns.command_args
        if not cmd:
            raise RuntimeErrorExit("exec needs a command after --", 2)
        return compose_action(prefix, env, "exec", "-T", f"wiki-{ns.language}", *cmd, check=False).returncode
    if ns.command == "update":
        compose_action(prefix, env, "up", "-d", "db", "wiki-fi", "wiki-sv", "wiki-en")
        for lang in LANGS:
            compose_action(prefix, env, "exec", "-T", f"wiki-{lang}", "php", "maintenance/run.php", "update", "--quick")
        return 0
    if ns.command == "status":
        m = manifest_value(project, root, ports, lock)
        healthy = True
        for lang in LANGS:
            ready = api_healthy(m["languages"][lang]["api_url"], expected_language=lang)
            healthy = healthy and ready
            print(f"{lang}: {'ready' if ready else 'not ready'} ({m['languages'][lang]['api_url']})")
        out = write_manifest(project, root, ports, lock)
        print(f"C1 manifest: {out}")
        return 0 if healthy else 1
    raise RuntimeErrorExit(f"Unknown command: {ns.command}", 2)


def main(argv: list[str] | None = None) -> int:
    try:
        return runtime_main(parser().parse_args(argv))
    except RuntimeErrorExit as exc:
        print(f"runtime: {exc}", file=sys.stderr)
        return exc.status
    except KeyboardInterrupt:
        print("runtime: interrupted; durable data was retained", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
