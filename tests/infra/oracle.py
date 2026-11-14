"""Independent acceptance checks for the frozen C1-C5 interchange contracts.

These checks deliberately consume manifests and source-fixture inventories. They
do not import runtime/data implementation code or infer behavior from log text.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from urllib.parse import urlparse


LANGUAGES = {"fi": "fiwiki", "sv": "svwiki", "en": "enwiki"}
FULL_COUNTS = {"fi": 19285, "sv": 4921, "en": 5254}


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _has_secret_key(value: object) -> bool:
    secret_names = {"password", "passwd", "token", "access_token", "secret", "api_key", "access_key"}
    if isinstance(value, dict):
        return any(
            str(key).lower() in secret_names or _has_secret_key(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_secret_key(child) for child in value)
    return False


def validate_runtime(manifest: dict, expected_project: str | None = None) -> list[str]:
    """Validate C1 identity, language routing, readiness and secret boundaries."""
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("C1 schema_version must be 1")
    if expected_project is not None and manifest.get("project") != expected_project:
        errors.append(f"C1 project does not match expected project {expected_project!r}")
    for field in ("project", "data_root", "ports", "languages", "versions", "initialized"):
        if field not in manifest:
            errors.append(f"C1 missing {field}")
    if _has_secret_key(manifest):
        errors.append("C1 contains a credential-bearing field")

    ports = manifest.get("ports")
    languages = manifest.get("languages")
    initialized = manifest.get("initialized")
    if not isinstance(ports, dict) or not isinstance(languages, dict) or not isinstance(initialized, dict):
        return errors + ["C1 ports, languages and initialized must be objects"]
    for language, source_wiki in LANGUAGES.items():
        if not isinstance(ports.get(language), int) or isinstance(ports.get(language), bool):
            errors.append(f"C1 {language} port must be an integer")
        details = languages.get(language)
        if not isinstance(details, dict):
            errors.append(f"C1 missing language details for {language}")
            continue
        for field in ("api_url", "service", "database"):
            if not details.get(field):
                errors.append(f"C1 {language} missing {field}")
        parsed = urlparse(str(details.get("api_url", "")))
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            errors.append(f"C1 {language} API URL must bind to localhost")
        if isinstance(ports.get(language), int) and parsed.port != ports[language]:
            errors.append(f"C1 {language} API URL port does not match its manifest port")
        if not isinstance(initialized.get(language), bool):
            errors.append(f"C1 {language} initialized state must be boolean")
    extra_languages = (set(ports) | set(languages) | set(initialized)) - set(LANGUAGES)
    if extra_languages:
        errors.append("C1 contains unexpected language keys: " + ", ".join(sorted(extra_languages)))
    return errors


def runtime_is_ready(manifest: dict, expected_project: str | None = None) -> bool:
    """A C1 manifest cannot imply readiness when a language is uninitialized."""
    return (
        not validate_runtime(manifest, expected_project)
        and all(manifest.get("initialized", {}).get(language) is True for language in LANGUAGES)
    )


def validate_corpus(manifest: dict) -> list[str]:
    """Validate C2 source identity, uniqueness and explicit sample/full scope."""
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("C2 schema_version must be 1")
    if manifest.get("scope") not in ("sample", "full"):
        errors.append("C2 scope must be sample or full")
    release = manifest.get("release")
    if not isinstance(release, dict) or not all(release.get(k) for k in ("repository", "tag")):
        errors.append("C2 release repository and tag are required")
    elif not isinstance(release.get("assets"), list):
        errors.append("C2 release assets must be a list")

    articles = manifest.get("articles")
    if not isinstance(articles, list):
        return errors + ["C2 articles must be a list"]
    counts = Counter()
    seen: set[tuple[str, int]] = set()
    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            errors.append(f"C2 article {index} must be an object")
            continue
        wiki = article.get("source_wiki")
        language = article.get("language")
        page_id = article.get("source_page_id")
        if wiki not in LANGUAGES.values() or LANGUAGES.get(language) != wiki:
            errors.append(f"C2 article {index} has inconsistent source wiki/language")
        if not _is_positive_int(page_id):
            errors.append(f"C2 article {index} source_page_id must be a positive integer")
        if not _is_positive_int(article.get("anchor_revision_id")):
            errors.append(f"C2 article {index} anchor_revision_id must be a positive integer")
        if not article.get("title") or not article.get("source_url"):
            errors.append(f"C2 article {index} needs a title and source_url")
        if article.get("wikidata_id") is not None and not isinstance(article.get("wikidata_id"), str):
            errors.append(f"C2 article {index} wikidata_id must be a string or null")
        if article.get("dataset_timestamp") is not None and not isinstance(article.get("dataset_timestamp"), str):
            errors.append(f"C2 article {index} dataset_timestamp must be a string or null")
        if wiki in LANGUAGES.values() and _is_positive_int(page_id):
            key = (wiki, page_id)
            if key in seen:
                errors.append(f"C2 duplicate source page key {wiki}:{page_id}")
            seen.add(key)
            counts[language] += 1
    expected = manifest.get("expected_counts")
    if not isinstance(expected, dict):
        errors.append("C2 expected_counts must be an object")
    else:
        for language in LANGUAGES:
            if expected.get(language) != counts[language]:
                errors.append(f"C2 {language} expected count does not match listed articles")
        if manifest.get("scope") == "full" and expected != FULL_COUNTS:
            errors.append("C2 full scope must retain the published per-language S counts")
    return errors


def verify_release_assets(release: dict, actual_assets: dict[str, bytes]) -> list[str]:
    """Recompute locked release size and SHA-256 before accepting fixture bytes."""
    errors: list[str] = []
    descriptors = release.get("assets")
    if not isinstance(descriptors, list):
        return ["release assets must be a list"]
    seen: set[str] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            errors.append("release asset descriptor must be an object")
            continue
        name = descriptor.get("name")
        if not name or name in seen:
            errors.append(f"release asset name missing or duplicated: {name!r}")
            continue
        seen.add(name)
        if not descriptor.get("url"):
            errors.append(f"release asset {name} has no source URL")
        data = actual_assets.get(name)
        if data is None:
            errors.append(f"release asset {name} is missing")
            continue
        if descriptor.get("size") != len(data):
            errors.append(f"release asset {name} size differs from lock")
        if descriptor.get("sha256") != sha256(data).hexdigest():
            errors.append(f"release asset {name} SHA-256 differs from lock")
    extra = set(actual_assets) - seen
    if extra:
        errors.append("unlocked release assets provided: " + ", ".join(sorted(extra)))
    return errors


def audit_pipeline(
    corpus: dict,
    expected_source_revisions: list[dict],
    history: list[dict],
    imports: list[dict],
    coverage: dict,
) -> list[str]:
    """Compare producer outputs with an independent, explicit source fixture.

    The independent revision inventory is intentional: a report cannot prove its
    own completeness by repeating its own acquired counts.
    """
    errors = validate_corpus(corpus)
    if coverage.get("schema_version") != 1:
        errors.append("C5 schema_version must be 1")
    for field in ("code_revision", "project", "generated_at", "release", "runtime_ready", "sample_verified", "rendering", "failures", "complete"):
        if field not in coverage:
            errors.append(f"C5 missing {field}")
    if coverage.get("scope") != corpus.get("scope"):
        errors.append("C5 scope differs from the requested corpus scope")
    if coverage.get("release") != corpus.get("release"):
        errors.append("C5 release identity differs from C2")
    if not isinstance(coverage.get("runtime_ready"), bool) or not isinstance(coverage.get("sample_verified"), bool):
        errors.append("C5 runtime_ready and sample_verified must be booleans")
    if not isinstance(coverage.get("rendering"), dict):
        errors.append("C5 rendering must be an object")

    articles = {
        (row.get("source_wiki"), row.get("source_page_id")): row
        for row in corpus.get("articles", [])
        if isinstance(row, dict)
    }
    expected_by_key: dict[tuple[str, int], dict] = {}
    for row in expected_source_revisions:
        key = (row.get("source_wiki"), row.get("source_revision_id"))
        if key in expected_by_key:
            errors.append(f"fixture contains duplicate expected revision {key[0]}:{key[1]}")
        expected_by_key[key] = row
        article_key = (row.get("source_wiki"), row.get("source_page_id"))
        if article_key not in articles:
            errors.append(f"expected history references page outside C2 membership: {article_key}")

    actual_by_key: dict[tuple[str, int], dict] = {}
    for row in history:
        key = (row.get("source_wiki"), row.get("source_revision_id"))
        if key in actual_by_key:
            prior = actual_by_key[key]
            if prior.get("computed_sha256") != row.get("computed_sha256"):
                errors.append(f"C3 conflicting content for source revision {key[0]}:{key[1]}")
            else:
                errors.append(f"C3 duplicate source revision {key[0]}:{key[1]}")
            continue
        actual_by_key[key] = row
        for field in (
            "source_page_id", "source_parent_id", "timestamp", "author", "comment", "comment_hidden",
            "minor", "content_model", "content_format", "content_hidden", "source_url",
            "acquisition_method", "acquired_at", "anchor_revision_id",
        ):
            if field not in row:
                errors.append(f"C3 missing {field} for {key[0]}:{key[1]}")
        if not _is_positive_int(row.get("source_revision_id")) or not _is_positive_int(row.get("source_page_id")):
            errors.append(f"C3 source IDs must be positive for {key[0]}:{key[1]}")
        author = row.get("author")
        if not isinstance(author, dict) or not isinstance(author.get("kind"), str) or not isinstance(author.get("hidden"), bool):
            errors.append(f"C3 author identity/visibility is invalid for {key[0]}:{key[1]}")
        if not isinstance(row.get("comment_hidden"), bool) or not isinstance(row.get("minor"), bool) or not isinstance(row.get("content_hidden"), bool):
            errors.append(f"C3 visibility/minor flags must be boolean for {key[0]}:{key[1]}")
        expected = expected_by_key.get(key)
        if expected is not None:
            comparable = (
                "source_page_id", "source_parent_id", "timestamp", "author", "comment",
                "comment_hidden", "minor", "content_model", "content_format", "content",
                "content_hidden", "source_sha1", "computed_sha256", "anchor_revision_id",
            )
            for field in comparable:
                if row.get(field) != expected.get(field):
                    errors.append(f"C3 {field} differs from source for {key[0]}:{key[1]}")
        if row.get("content") is not None:
            digest = sha256(row["content"].encode("utf-8")).hexdigest()
            if row.get("computed_sha256") != digest:
                errors.append(f"C3 inline content hash is wrong for {key[0]}:{key[1]}")
        if (row.get("source_wiki"), row.get("source_page_id")) not in articles:
            errors.append(f"C3 history references page outside C2 membership: {key[0]}:{row.get('source_page_id')}")
        if row.get("content_hidden") is True and row.get("content") is not None:
            errors.append(f"C3 hidden content is exposed for {key[0]}:{key[1]}")
        if row.get("content_hidden") is False and row.get("content") is None and not row.get("content_ref"):
            errors.append(f"C3 visible content is unavailable for {key[0]}:{key[1]}")
        if row.get("comment_hidden") is True and row.get("comment") is not None:
            errors.append(f"C3 hidden comment is exposed for {key[0]}:{key[1]}")
        if not str(row.get("timestamp", "")).endswith("Z"):
            errors.append(f"C3 timestamp must be UTC ISO8601 for {key[0]}:{key[1]}")

    missing_history = set(expected_by_key) - set(actual_by_key)
    extra_history = set(actual_by_key) - set(expected_by_key)
    if missing_history:
        errors.append("C3 missing source revisions: " + _format_keys(missing_history))
    if extra_history:
        errors.append("C3 has revisions outside the expected source inventory: " + _format_keys(extra_history))

    anchors = {
        (row.get("source_wiki"), row.get("anchor_revision_id"))
        for row in corpus.get("articles", [])
        if isinstance(row, dict)
    }
    for wiki, anchor_id in anchors:
        if (wiki, anchor_id) not in actual_by_key:
            errors.append(f"C3 missing validated snapshot anchor {wiki}:{anchor_id}")

    imports_by_key: dict[tuple[str, int], dict] = {}
    local_revisions: dict[tuple[object, object, object], tuple[str, int]] = {}
    for row in imports:
        key = (row.get("source_wiki"), row.get("source_revision_id"))
        if key in imports_by_key:
            errors.append(f"C4 duplicate mapping for source revision {key[0]}:{key[1]}")
            continue
        imports_by_key[key] = row
        for field in (
            "source_page_id", "source_parent_id", "local_page_id", "local_revision_id",
            "source_content_hash", "timestamp", "author", "batch_checksum", "status", "errors",
        ):
            if field not in row:
                errors.append(f"C4 missing {field} for {key[0]}:{key[1]}")
        if key not in expected_by_key:
            errors.append(f"C4 maps a source revision outside the expected inventory: {key[0]}:{key[1]}")
        if not row.get("local_page_id") or not row.get("local_revision_id"):
            errors.append(f"C4 missing local identity for {key[0]}:{key[1]}")
        local_key = (key[0], row.get("local_page_id"), row.get("local_revision_id"))
        if local_key in local_revisions and local_revisions[local_key] != key:
            errors.append(f"C4 local identity reused for different source revisions: {local_key}")
        local_revisions[local_key] = key
        source = actual_by_key.get(key)
        if source is not None and row.get("source_content_hash") != source.get("computed_sha256"):
            errors.append(f"C4 source content hash mismatch for {key[0]}:{key[1]}")
        expected_source = expected_by_key.get(key)
        if expected_source is not None:
            for field in ("source_page_id", "source_parent_id", "timestamp"):
                if row.get(field) != expected_source.get(field):
                    errors.append(f"C4 {field} differs from source for {key[0]}:{key[1]}")
            source_author = expected_source.get("author")
            imported_author = row.get("author")
            if isinstance(source_author, dict) and isinstance(imported_author, dict):
                for field in ("kind", "value", "hidden"):
                    if imported_author.get(field) != source_author.get(field):
                        errors.append(f"C4 author.{field} differs from source for {key[0]}:{key[1]}")
            else:
                errors.append(f"C4 author representation is missing for {key[0]}:{key[1]}")
        if row.get("errors"):
            errors.append(f"C4 mapping has errors for {key[0]}:{key[1]}")
    missing_imports = set(expected_by_key) - set(imports_by_key)
    if missing_imports:
        errors.append("C4 missing source mappings: " + _format_keys(missing_imports))

    per_language = coverage.get("per_language")
    if not isinstance(per_language, dict):
        errors.append("C5 per_language must be an object")
        per_language = {}
    for language, wiki in LANGUAGES.items():
        summary = per_language.get(language)
        if not isinstance(summary, dict):
            errors.append(f"C5 missing per-language summary for {language}")
            continue
        language_articles = {
            key for key, row in articles.items() if row.get("language") == language
        }
        article_count = len(language_articles)
        expected_keys = {key for key in expected_by_key if key[0] == wiki}
        actual_keys = {key for key in actual_by_key if key[0] == wiki}
        imported_keys = {key for key in imports_by_key if key[0] == wiki}
        expected_rev_count = len(expected_keys)
        actual_rev_count = len(actual_keys)
        imported_rev_count = len(imported_keys)
        reconciled_keys = {
            key for key in (expected_keys & actual_keys & imported_keys)
            if imports_by_key[key].get("source_content_hash") == actual_by_key[key].get("computed_sha256")
            and not imports_by_key[key].get("errors")
        }
        language_page_ids = {page_id for _, page_id in language_articles}
        acquired_page_ids = {
            row.get("source_page_id") for row in actual_by_key.values()
            if row.get("source_wiki") == wiki
        }
        imported_page_ids = {
            row.get("source_page_id") for key, row in imports_by_key.items()
            if key[0] == wiki
        }
        reconciled_page_ids = {
            page_id for source_wiki, page_id in language_articles
            if {key for key in expected_keys if expected_by_key[key].get("source_page_id") == page_id}
            <= reconciled_keys
        }
        required_counts = {
            "expected_articles": article_count,
            "acquired_articles": len(language_page_ids & acquired_page_ids),
            "imported_articles": len(language_page_ids & imported_page_ids),
            "reconciled_articles": len(reconciled_page_ids),
            "expected_revisions": expected_rev_count,
            "acquired_revisions": actual_rev_count,
            "imported_revisions": imported_rev_count,
            "reconciled_revisions": len(reconciled_keys),
            "unresolved_pages": article_count - len(reconciled_page_ids),
            "unresolved_revisions": expected_rev_count - len(reconciled_keys),
        }
        for field, value in required_counts.items():
            if summary.get(field) != value:
                errors.append(f"C5 {language} {field}={summary.get(field)!r}, expected {value}")

    failures = coverage.get("failures")
    if not isinstance(failures, list):
        errors.append("C5 failures must be a list")
        failures = []
    should_be_complete = not errors and not failures
    if coverage.get("complete") is not should_be_complete:
        errors.append(f"C5 complete={coverage.get('complete')!r} disagrees with audited state")
    return errors


def _format_keys(keys: set[tuple[str, int]]) -> str:
    return ", ".join(f"{wiki}:{revision}" for wiki, revision in sorted(keys))
