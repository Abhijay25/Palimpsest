"""Create clearly synthetic pages through MediaWiki's ordinary account/edit APIs.

This script never starts, stops, resets, or changes runtime configuration. It
requires the operator to name the authorized feature project and writes a
credential-free state manifest outside the repository for browser assertions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import string
import sys
import uuid

from mediawiki_api import MediaWikiApiError, WikiApi


ROOT = Path(__file__).resolve().parents[2]
LANGS = ("fi", "sv", "en")
FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_IDS = (
    "cross_contributor_deletion", "chained_replacements", "repeated_move_revert",
    "unicode_utf16_selection", "date_boundaries", "large_unique_anchor_history",
)
BROWSER_FIXTURE_IDS = (
    "rendered_mapped_selection", "generated_unmapped_selection",
    "fragmented_selection", "paragraph_boundary_selection",
)
DOCKER_PROJECT = "palimpsest-blame"
AUTHORS = ("FixtureAlice", "FixtureBoris", "FixtureChandra", "FixtureDara")


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("project") != DOCKER_PROJECT:
        raise ValueError(f"manifest must identify authorized project {DOCKER_PROJECT}")
    ports = data.get("ports") or {}
    if ports != {"fi": 48081, "sv": 48082, "en": 48083}:
        raise ValueError("manifest ports do not match the root-owned feature runtime")
    languages = data.get("languages") or {}
    if set(languages) != set(LANGS):
        raise ValueError("manifest must contain fi, sv and en")
    return data


def make_password() -> str:
    alphabet = string.ascii_letters + string.digits + "-_.!"
    return "P" + "".join(secrets.choice(alphabet) for _ in range(30))


def fixture(fixture_id: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))


def seed_language(language: str, api_url: str, run_id: str, *, include_job_history: bool = False) -> tuple[dict, dict]:
    account_names = {alias: f"PB{run_id}{alias.removeprefix('Fixture')}" for alias in AUTHORS}
    passwords = {alias: make_password() for alias in AUTHORS}
    anonymous = WikiApi(api_url)
    for alias in AUTHORS:
        anonymous.create_account(account_names[alias], passwords[alias])
    editor_name = f"PB{run_id}LocalEditor"
    editor_password = make_password()
    anonymous.create_account(editor_name, editor_password)

    clients: dict[str, WikiApi] = {}
    for alias in AUTHORS:
        client = WikiApi(api_url)
        client.login(account_names[alias], passwords[alias])
        clients[alias] = client

    pages = {}
    for fixture_id in FIXTURE_IDS:
        doc = fixture(fixture_id)
        title = f"PalimpsestBlameSynthetic/{run_id}/{fixture_id}"
        revisions = []
        for revision in doc["revisions"]:
            new_id = clients[revision["author"]].edit(
                title,
                revision["text"],
                f"[synthetic Blame acceptance fixture {run_id}] {revision['alias']}",
            )
            revisions.append({"alias": revision["alias"], "revision_id": new_id, "author": account_names[revision["author"]]})
        pages[fixture_id] = {"title": title, "revisions": revisions}

    browser_pages = {}
    for fixture_id in BROWSER_FIXTURE_IDS:
        doc = fixture(fixture_id)
        title = f"PalimpsestBlameSynthetic/{run_id}/{fixture_id}"
        if fixture_id == "rendered_mapped_selection":
            target_title = f"PalimpsestBlameSynthetic/{run_id}/ordinary_link_target"
            target_text = doc["link_target_text"]
            target_revision_id = clients["FixtureAlice"].edit(
                target_title, target_text, f"[synthetic Blame fixture {run_id}] ordinary link target",
            )
            browser_pages["ordinary_link_target"] = {
                "title": target_title, "revision_id": target_revision_id,
                "source_text": target_text,
            }
            text = doc["wikitext"].replace("LINK_TARGET", target_title)
        elif fixture_id == "generated_unmapped_selection":
            template_title = f"Template:PalimpsestBlameSynthetic/{run_id}/Generated"
            clients["FixtureAlice"].edit(template_title, doc["template_wikitext"], f"[synthetic Blame fixture {run_id}] template")
            text = doc["wikitext_template"].replace("{{template_title}}", "{{" + template_title.removeprefix("Template:") + "}}")
            browser_pages["generated_template_title"] = template_title
        elif fixture_id == "fragmented_selection":
            text = " ".join(f"''{token}''" if index % 2 else token for index, token in enumerate(doc["tokens"]))
        else:
            text = doc["wikitext"]
        revision_id = clients["FixtureAlice"].edit(title, text, f"[synthetic Blame rendered fixture {run_id}] {fixture_id}")
        browser_pages[fixture_id] = {"title": title, "revision_id": revision_id, "author": account_names["FixtureAlice"], "source_text": text}
    language_state = {"language": language, "api_url": api_url, "users": account_names, "pages": pages, "browser_pages": browser_pages}
    if include_job_history:
        title = f"PalimpsestBlameSynthetic/{run_id}/job_resume_205"
        revision_ids = []
        for index in range(205):
            text = f"job fixture revision {index:03d} common prefix anchor{index:03d} common suffix"
            author = AUTHORS[index % len(AUTHORS)]
            revision_id = clients[author].edit(
                title,
                text,
                f"[synthetic Blame bounded job fixture {run_id}] revision {index:03d}",
            )
            revision_ids.append(revision_id)
        language_state["job_resume"] = {
            "title": title,
            "revision_ids": revision_ids,
            "revision_count": len(revision_ids),
            "expected_text": "job fixture revision 204 common prefix anchor204 common suffix",
        }
    editor_auth = {"username": editor_name, "password": editor_password}
    return language_state, editor_auth


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="root-owned C1 feature runtime manifest")
    parser.add_argument("--confirm-project", required=True, help="must be exactly palimpsest-blame")
    parser.add_argument("--state-file", type=Path, required=True, help="credential-free state file outside the checkout")
    parser.add_argument("--auth-file", type=Path, required=True, help="private synthetic editor credentials outside the repository")
    parser.add_argument("--include-job-history", action="store_true", help="create a bounded 205-revision synthetic page for async job tests")
    args = parser.parse_args()
    if args.confirm_project != DOCKER_PROJECT:
        parser.error(f"--confirm-project must be {DOCKER_PROJECT}")
    try:
        if args.state_file.resolve().is_relative_to(ROOT) or args.auth_file.resolve().is_relative_to(ROOT):
            raise ValueError("state and credential files must stay outside the repository")
        if args.state_file.resolve() == args.auth_file.resolve():
            raise ValueError("state manifest and private credentials must use separate files")
        manifest = load_manifest(args.manifest)
        run_id = uuid.uuid4().hex[:10]
        seeded = {
            lang: seed_language(lang, manifest["languages"][lang]["api_url"], run_id, include_job_history=args.include_job_history)
            for lang in LANGS
        }
        state = {
            "schema_version": 1,
            "scope": "synthetic_only",
            "project": DOCKER_PROJECT,
            "run_id": run_id,
            "languages": {lang: seeded[lang][0] for lang in LANGS},
        }
        auth = {
            "scope": "synthetic_test_accounts_only",
            "project": DOCKER_PROJECT,
            "run_id": run_id,
            "languages": {lang: seeded[lang][1] for lang in LANGS},
        }
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.state_file.chmod(0o600)
        args.auth_file.parent.mkdir(parents=True, exist_ok=True)
        args.auth_file.write_text(json.dumps(auth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.auth_file.chmod(0o600)
    except (OSError, ValueError, KeyError, TypeError, MediaWikiApiError) as exc:
        print(f"FAIL synthetic fixture setup: {exc}", file=sys.stderr)
        return 1
    print(f"SEEDED run={run_id} project={DOCKER_PROJECT} languages=fi,sv,en history_pages_per_language={len(FIXTURE_IDS)} browser_pages_per_language={len(BROWSER_FIXTURE_IDS)}")
    print(f"STATE {args.state_file}")
    print(f"PRIVATE_AUTH {args.auth_file}")
    print("No feature API assertion was run; install the reviewed extension before live acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
