"""Methodology transformation contracts: normalization, validation, README rendering.

A transformation is a *rule/decision* extracted from completed migrations, not
a code artifact.  The published component therefore contains:

* source/target patterns (APIs and mechanisms, not file paths);
* mapping rules, semantic deltas, pitfalls;
* a procedure, verification strategy and boundary;
* provenance evidence at project/commit/task granularity.

The validator deliberately rejects anything that could smuggle a specific
implementation into the library: absolute paths, source-file paths, fenced
code, `#include` lines and project file names seen in the history corpus.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

TRANSFORMATION_SCHEMA = "transformation-draft-v1"
COMPONENT_KIND = "transformation"
STATUSES = {"draft_ready", "uncertain", "not_extractable"}
RESPONSE_STATUSES = {"ready", "uncertain"}
EVIDENCE_ROLES = {"source-migration", "replay", "test", "review"}

# Free-form capability labels are accepted, but the prompt recommends this
# vocabulary so retrieval and playbook joins can group components.
CAPABILITY_VOCABULARY = {
    "platform-abstraction",
    "file-system/io",
    "file-system/metadata",
    "process",
    "ipc",
    "threading",
    "synchronization",
    "dynamic-loading",
    "error-handling",
    "time",
    "memory",
    "build",
    "networking",
    # Cross-scenario labels (CUDA→MUSA, IPP→VSIPL, ...).
    "gpu-compute",
    "memory-transfer",
    "launch-config",
    "signal-processing",
    "vector-math",
    "numerical-tolerance",
    "other",
}

# The agent contract is the experience card.  Ids, the capability label and the
# target environment are pipeline-owned and are not shown back to agents.
CARD_FIELDS = (
    "title",
    "when_to_use",
    "mapping_rules",
    "semantic_deltas",
    "pitfalls",
    "procedure",
    "verification",
    "boundary",
    "applicability",
)

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_SOURCE_SUFFIX = r"(?:c|h|cc|cpp|cxx|hh|hpp|hxx|m|mm|py|rs|go|java|js|ts|tsx)"
_PATH_WITH_SUFFIX_RE = re.compile(
    rf"(?:^|[\s`'\"(<\[])((?:[\w.+-]+/)+[\w.+-]+\.{_SOURCE_SUFFIX})(?=$|[\s`'\")>\].,:;])"
)
_ABSOLUTE_RE = re.compile(
    r"(?:^|[\s`'\"])"
    r"(?:/(?:home|usr|opt|var|tmp|root|etc|mnt|srv|workspace|testbed|component-output)(?:/|\b)"
    r"|~[/\\]|[A-Za-z]:[\\/])"
)
_INCLUDE_RE = re.compile(r"^\s*#\s*include\b", re.MULTILINE)
_FENCE_RE = re.compile(r"```")
# Standard system header directories name a platform API, not a source file.
_SYSTEM_HEADER_RE = re.compile(
    r"^(?:sys|linux|asm|asm-generic|net|netinet|arpa|bits|machine|api/sys)"
    r"/[\w.+-]+\.(?:h|hh|hpp|hxx)$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _text(
    value: Any, field: str, *, minimum: int = 1, maximum: int | None = 2000
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = " ".join(value.split())
    if len(value) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return value


def _optional_text(
    value: Any, field: str, *, maximum: int | None = 2000
) -> str:
    if value in (None, ""):
        return ""
    return _text(value, field, minimum=1, maximum=maximum)


def _text_list(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum_items: int | None = None,
    maximum_length: int | None = None,
) -> list[str]:
    """Accept prose or a list.

    A paragraph is one entry.  Content fields do not impose item or length
    limits: the card is judged on what it says, not on how it is shaped.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a string or a list of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        text = _text(item, f"{field}[{index}]", maximum=maximum_length)
        # Agents often prefix list items with their own bullet; the renderer
        # adds one, so keep the text and drop the marker.
        text = _BULLET_RE.sub("", text, count=1)
        if text not in items:
            items.append(text)
    if len(items) < minimum:
        raise ValueError(f"{field} needs at least {minimum} distinct entries")
    if maximum_items is not None and len(items) > maximum_items:
        raise ValueError(f"{field} has more than {maximum_items} entries")
    return items


def _string_list(
    value: Any, field: str, *, maximum_items: int | None = 20
) -> list[str]:
    if value in (None, ""):
        return []
    return _text_list(value, field, minimum=0, maximum_items=maximum_items)


def _slug(value: str, field: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-.")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug or len(slug) > 64 or not re.match(r"^[a-z0-9][a-z0-9._-]*$", slug):
        raise ValueError(f"{field} must be a stable lowercase identifier: {value!r}")
    return slug




def _target_os(example: dict[str, Any]) -> list[str]:
    """Target environment, owned by the corpus rather than the model."""
    target = example.get("target") or {}
    values = [
        str(target.get(key) or "").strip()
        for key in ("os", "arch")
    ]
    return [value for value in values if value] or ["unspecified"]


def _applicability(value: Any, *, os_values: list[str]) -> dict[str, Any]:
    """The model supplies constraints; the corpus supplies the environment."""
    if value in (None, ""):
        value = {}
    if not isinstance(value, dict):
        raise ValueError("applicability must be an object")
    constraints = _string_list(
        value.get("constraints"), "applicability.constraints", maximum_items=None
    )
    return {"os": list(os_values), "constraints": constraints}


def _capability_from_example(example: dict[str, Any]) -> str:
    """The migration task already declares the layer; inherit it."""
    value = str(example.get("capability") or "").strip().lower().replace(" ", "-")
    return value if value in CAPABILITY_VOCABULARY else "other"


def _evidence(value: Any) -> list[dict[str, Any]]:
    """Normalize explicit evidence; the pipeline always attaches its own."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("evidence must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"evidence[{index}] must be an object")
        project = _text(item.get("project"), f"evidence[{index}].project", maximum=120)
        task_id = _text(item.get("task_id"), f"evidence[{index}].task_id", maximum=160)
        commit = _optional_text(item.get("commit"), f"evidence[{index}].commit", maximum=80)
        role = str(item.get("role") or "source-migration").strip().lower()
        if role not in EVIDENCE_ROLES:
            raise ValueError(f"evidence[{index}].role must be one of {sorted(EVIDENCE_ROLES)}")
        note = _optional_text(item.get("note"), f"evidence[{index}].note", maximum=400)
        key = (project.lower(), task_id, commit)
        if key in seen:
            continue
        seen.add(key)
        record = {"project": project, "commit": commit, "task_id": task_id, "role": role}
        if note:
            record["note"] = note
        normalized.append(record)
    return normalized


def _derive_id(title: str) -> str:
    """Derive a stable id from the card title.

    Titles are human-facing and may be non-ASCII; fall back to a short digest
    so every component still has a stable identifier.  An over-long title is
    cut at a word boundary and tagged with a short digest, never mid-word.
    """
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-.")
    slug = re.sub(r"-{2,}", "-", slug).strip("-.")
    if len(slug) < 3:
        return "component-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    if len(slug) <= 64:
        return slug
    suffix = "-" + hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
    head = slug[: 64 - len(suffix)]
    cut = head.rsplit("-", 1)[0].strip("-.")
    if len(cut) < 24:
        cut = head.strip("-.")
    return cut + suffix


def normalize_transformation(
    value: dict[str, Any],
    *,
    example: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one agent-produced transformation into the internal shape."""
    if not isinstance(value, dict):
        raise ValueError("transformation must be an object")
    status = str(value.get("status") or "draft_ready").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"transformation status must be one of {sorted(STATUSES)}")
    title = _text(value.get("title"), "title", minimum=5, maximum=None)
    # Identity is deterministic: the pipeline names every component from its
    # title.  A model-supplied id is ignored so a repair cannot rename a family.
    transformation_id = _derive_id(title)
    when_to_use = _text(value.get("when_to_use"), "when_to_use", minimum=20, maximum=None)
    mapping_rules = _text_list(value.get("mapping_rules"), "mapping_rules")
    semantic_deltas = _text_list(value.get("semantic_deltas"), "semantic_deltas")
    pitfalls = _text_list(value.get("pitfalls"), "pitfalls")
    procedure = _text_list(value.get("procedure"), "procedure")
    verification = _text_list(value.get("verification"), "verification")
    boundary = _text(value.get("boundary"), "boundary", minimum=20, maximum=None)
    applicability = _applicability(
        value.get("applicability"), os_values=_target_os(example)
    )
    evidence = _evidence(value.get("evidence"))
    capability = _capability_from_example(example)

    # The corpus provenance is authoritative: always attach it so a component
    # cannot claim a migration it was not extracted from.
    source_meta = example.get("source") or {}
    project = str(source_meta.get("repo") or "").rsplit("/", 1)[-1].removesuffix(".git")
    canonical = {
        "project": project,
        "commit": str(source_meta.get("commit") or ""),
        "task_id": str(example.get("task_id") or ""),
        "role": "source-migration",
    }
    if not any(
        item["project"].lower() == canonical["project"].lower()
        and item["task_id"] == canonical["task_id"]
        and item["commit"] == canonical["commit"]
        for item in evidence
    ):
        evidence.insert(0, canonical)

    return {
        "schema": TRANSFORMATION_SCHEMA,
        "status": status,
        "transformation_id": transformation_id,
        "title": title,
        "capability": capability,
        "when_to_use": when_to_use,
        "mapping_rules": mapping_rules,
        "semantic_deltas": semantic_deltas,
        "pitfalls": pitfalls,
        "procedure": procedure,
        "verification": verification,
        "boundary": boundary,
        "applicability": applicability,
        "evidence": evidence,
        "notes": _optional_text(value.get("notes"), "notes", maximum=2000),
    }


def _iter_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(item, f"{path}.{key}" if path else str(key))


def _flatten_text(value: Any) -> str:
    return " ".join(text for _, text in _iter_strings(value))


def _normalize_quote(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def field_text(transformation: dict[str, Any], field: str) -> str | None:
    """The searchable text of one card field; ``None`` for an unknown field."""
    if field not in CARD_FIELDS:
        return None
    return _flatten_text(transformation.get(field))


def quote_present(transformation: dict[str, Any], field: str, quote: str) -> bool:
    """Whether ``quote`` still appears in ``field`` (whitespace-insensitive)."""
    if not isinstance(field, str) or not isinstance(quote, str):
        return False
    text = field_text(transformation, field)
    if text is None:
        return False
    needle = _normalize_quote(quote)
    return bool(needle) and needle in _normalize_quote(text)


def _project_prefix(example: dict[str, Any]) -> str:
    """The source project's identifier prefix, e.g. ``uv_`` from its API list."""
    symbols = [str(item) for item in example.get("api_symbols") or []]
    if len(symbols) < 2:
        return ""
    prefix = os.path.commonprefix(symbols)
    if not prefix.endswith("_"):
        prefix = prefix[: prefix.rfind("_") + 1]
    return prefix.lower() if len(prefix) >= 2 else ""


def _private_tokens(example: dict[str, Any]) -> dict[str, str]:
    """Corpus names that must not appear in a component, and what they are."""
    tokens: dict[str, str] = {}
    for items in (example.get("files") or {}).values():
        for relative in items or []:
            name = Path(relative).name.lower()
            tokens.setdefault(name, "corpus file")
            stem = Path(name).stem.lower()
            if len(stem) >= 4 and ("-" in stem or "_" in stem or any(ch.isdigit() for ch in stem)):
                tokens.setdefault(stem, "corpus file")
    repo = str((example.get("source") or {}).get("repo") or "").rstrip("/")
    repo = repo.rsplit("/", 1)[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if len(repo) >= 3:
        tokens.setdefault(repo.lower(), "source project")
    task_id = str(example.get("task_id") or "")
    if len(task_id) >= 3:
        tokens.setdefault(task_id.lower(), "example id")
    return tokens


def leakage_findings(
    transformation: dict[str, Any],
    *,
    example: dict[str, Any] | None = None,
) -> list[str]:
    """Return strings that would leak a specific implementation into the library.

    Provenance fields (``evidence`` and ``provenance``) are exempt: project,
    commit and task IDs are the intended citation form.  Everything else stays
    rule-level, so a component may not name this corpus's files, project or
    identifiers.
    """
    tokens = _private_tokens(example) if example else {}
    prefix = _project_prefix(example) if example else ""
    prefix_re = (
        re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(prefix)}[A-Za-z0-9_]*", re.IGNORECASE
        )
        if prefix
        else None
    )
    findings: list[str] = []
    for path, text in _iter_strings(transformation):
        if path.startswith("evidence") or path.startswith("provenance"):
            continue
        if _FENCE_RE.search(text):
            findings.append(f"{path}: contains a fenced code block")
            continue
        if _INCLUDE_RE.search(text):
            findings.append(f"{path}: contains an include directive")
            continue
        if _ABSOLUTE_RE.search(text):
            findings.append(f"{path}: contains an absolute path")
            continue
        match = _PATH_WITH_SUFFIX_RE.search(text)
        if match and not _SYSTEM_HEADER_RE.match(match.group(1)):
            findings.append(f"{path}: contains a source path ({match.group(1)})")
            continue
        if prefix_re is not None:
            match = prefix_re.search(text)
            if match:
                findings.append(
                    f"{path}: names a source-project identifier ({match.group(0)})"
                )
                continue
        if (
            " -> " not in text
            and re.search(r"(?<![A-Za-z0-9_])[a-z][a-z0-9_]{0,7}->[a-z_][a-z0-9_]*", text)
        ):
            findings.append(f"{path}: contains source-level member access")
            continue
        for token, label in tokens.items():
            if re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w.-])", text, re.IGNORECASE):
                findings.append(f"{path}: names a {label} ({token})")
                break
        else:
            if len(text) > 400 and ";" in text and ("{" in text or "}" in text):
                findings.append(f"{path}: looks like copied code")
    return findings


def validate_transformation(
    transformation: dict[str, Any],
    *,
    example: dict[str, Any],
) -> list[str]:
    """Validate a normalized transformation against its source example."""
    errors: list[str] = []
    if transformation.get("schema") != TRANSFORMATION_SCHEMA:
        errors.append(f"schema must be {TRANSFORMATION_SCHEMA}")
    if transformation.get("status") != "draft_ready":
        errors.append("only draft_ready transformations can be published")
    evidence = transformation.get("evidence") or []
    source = example.get("source") or {}
    project = str(source.get("repo") or "").rsplit("/", 1)[-1].removesuffix(".git").lower()
    commit = str(source.get("commit") or "")
    task_id = str(example.get("task_id") or "")
    grounded = [
        item for item in evidence
        if str(item.get("project", "")).lower() == project
        and str(item.get("task_id", "")) == task_id
        and str(item.get("commit", "")) == commit
    ]
    if not grounded:
        errors.append("evidence does not cite this example's project, commit and task")
    if transformation.get("capability") not in CAPABILITY_VOCABULARY:
        errors.append("capability is not in the taxonomy")
    errors.extend(leakage_findings(transformation, example=example))
    return errors


def normalize_response(
    response: dict[str, Any],
    *,
    example: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Validate the extraction envelope and normalize every transformation.

    Returns ``(status, accepted, workspace_audit, rejected)``.
    """
    if not isinstance(response, dict):
        raise ValueError("methodology extraction response must be a JSON object")
    raw_items = response.get("transformations") or []
    if not isinstance(raw_items, list):
        raise ValueError("transformations must be a list")
    if len(raw_items) != 1:
        # The unit is the corpus example: its count is fixed by the corpus,
        # never by how finely the model chooses to slice its output.
        raise ValueError(
            "one example yields exactly one component; the response contained "
            f"{len(raw_items)}"
        )
    status = str(response.get("status") or "ready").strip().lower()
    if status not in RESPONSE_STATUSES:
        raise ValueError(f"extraction status must be one of {sorted(RESPONSE_STATUSES)}")
    # The workspace audit is optional machine bookkeeping.  It is no longer
    # part of the agent contract, but legacy runs may still provide it, in
    # which case its coverage check remains enforced.
    audit = response.get("workspace_audit") or {}
    if not isinstance(audit, dict):
        raise ValueError("workspace_audit must be an object")
    checked = audit.get("checked_files") or []
    gaps = audit.get("gaps") or []
    if not isinstance(checked, list) or not all(isinstance(item, str) for item in checked):
        raise ValueError("workspace_audit.checked_files must be a list of paths")
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        raise ValueError("workspace_audit.gaps must be a list of strings")
    if checked:
        expected = [*example["files"]["after"], *example["files"]["before"]]
        missing = sorted(set(expected) - set(checked))
        if missing:
            raise ValueError(f"agent did not inspect every before/after file: {missing}")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_items):
        try:
            transformation = normalize_transformation(item, example=example)
            errors = validate_transformation(transformation, example=example)
        except ValueError as exc:
            rejected.append({"index": index, "errors": [str(exc)]})
            continue
        if errors:
            rejected.append(
                {
                    "index": index,
                    "transformation_id": transformation.get("transformation_id"),
                    "errors": errors,
                }
            )
            continue
        if transformation["transformation_id"] in seen:
            rejected.append(
                {
                    "index": index,
                    "transformation_id": transformation["transformation_id"],
                    "errors": ["duplicate transformation_id in one response"],
                }
            )
            continue
        seen.add(transformation["transformation_id"])
        accepted.append(transformation)
    return status, accepted, audit, rejected


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _field_block(items: list[str]) -> list[str]:
    """Prose stays prose; only a real set of statements becomes a bullet list."""
    if len(items) == 1:
        return [items[0], ""]
    return [*(f"- {item}" for item in items), ""]


def _procedure_block(steps: list[str]) -> list[str]:
    if len(steps) == 1:
        return [steps[0], ""]
    return [*(f"{index}. {step}" for index, step in enumerate(steps, 1)), ""]


def render_readme(component: dict[str, Any]) -> str:
    """Render the published Markdown from normalized component fields."""
    applicability = component["applicability"]
    provenance = component.get("provenance") or {}
    derived = provenance.get("task_ids") or []
    lines = [
        f"# {component['title']}",
        "",
        f"- Kind: {COMPONENT_KIND}",
        f"- Capability: `{component['capability']}`",
        f"- Derived from: {', '.join(f'`{item}`' for item in derived)}",
        f"- Applies to: {', '.join(applicability['os'])}",
        "",
        "## When to use",
        "",
        component["when_to_use"],
        "",
        "## Procedure",
        "",
        *_procedure_block(component["procedure"]),
        "## Mapping rules",
        "",
        *_field_block(component["mapping_rules"]),
        "## Semantic deltas to expect",
        "",
        *_field_block(component["semantic_deltas"]),
        "## Pitfalls observed in successful migrations",
        "",
        *_field_block(component["pitfalls"]),
        "## Verification strategy",
        "",
        *_field_block(component["verification"]),
        "## Boundary",
        "",
        component["boundary"],
        "",
    ]
    if applicability["constraints"]:
        lines.extend(
            [
                "Applicability constraints:",
                "",
                *[f"- {item}" for item in applicability["constraints"]],
                "",
            ]
        )
    if component.get("notes"):
        lines.extend(["## Notes", "", component["notes"], ""])
    return "\n".join(lines)


def component_metadata(
    transformation: dict[str, Any],
    *,
    bundle_id: str,
    review: dict[str, Any] | None,
    input_digest: str,
) -> dict[str, Any]:
    """Build the published ``component.json`` (catalog-compatible)."""
    evidence = transformation["evidence"]
    projects = sorted({item["project"] for item in evidence})
    commits = sorted({item["commit"] for item in evidence if item.get("commit")})
    task_ids = sorted({item["task_id"] for item in evidence})
    return {
        "bundle_id": bundle_id,
        "kind": COMPONENT_KIND,
        "title": transformation["title"],
        "capability": transformation["capability"],
        "when_to_use": transformation["when_to_use"],
        "boundary": transformation["boundary"],
        "verification": transformation["verification"],
        "mapping_rules": transformation["mapping_rules"],
        "semantic_deltas": transformation["semantic_deltas"],
        "pitfalls": transformation["pitfalls"],
        "procedure": transformation["procedure"],
        "applicability": transformation["applicability"],
        "provenance": {
            "projects": projects,
            "commits": commits,
            "task_ids": task_ids,
            "split": "dev",
        },
        "evidence": evidence,
        "generated_by": "component_method.component_build.methodology.publish",
        "input_digest": input_digest,
        "review": (
            {
                "verdict": review.get("verdict"),
                "reviewer_model": review.get("model"),
                "review_sha256": review.get("review_sha256"),
                "finalized": bool(review.get("finalized")),
            }
            if review
            else {"verdict": "unreviewed"}
        ),
    }