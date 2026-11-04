"""Consumer metadata: actual signatures and independently checked capability scopes."""

from __future__ import annotations

import ast
from typing import Any

from ..component_build.workspace import COMPONENT_DIRECTORY


def _short(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def component_card(item: dict[str, Any], source: str, bundle_id: str, library: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = ast.Module(body=[], type_ignores=[])
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
            if isinstance(node, ast.ClassDef):
                definitions.update({f"{node.name}.{child.name}": child for child in node.body
                                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))})
    validation = item.get("local_validation", {}).get("validation", {})
    capabilities = validation.get("entrypoint_capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("component publication requires current entrypoint_capabilities")
    from ..component_build.validation.service import _unreported_class_paths
    capabilities = capabilities + _unreported_class_paths(source, item.get("entrypoints", []), capabilities)
    origins = [{"file": member.get("file_id"), "symbol": str(member.get("unit_id", "")).split(":", 1)[-1]}
               for member in item.get("members", []) if isinstance(member, dict)]
    entries = []
    for cap in capabilities:
        name = cap.get("entrypoint", "")
        path = cap.get("path") or name
        symbol = path.split("(", 1)[0]
        node = definitions.get(symbol) or definitions.get(name)
        signature = ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = f"{symbol}({ast.unparse(node.args)})"
            if node.returns:
                signature += " -> " + ast.unparse(node.returns)
        elif isinstance(node, ast.ClassDef):
            init = definitions.get(f"{name}.__init__")
            signature = f"{name}({ast.unparse(init.args)})" if init else f"class {name}"
        matched = [origin for origin in origins if origin["symbol"] in {name, symbol}]
        entries.append({
            "entrypoint": name, "path": path, "signature": signature,
            "source": matched or origins, "contract": str(cap.get("contract") or ""),
            "example": str(cap.get("example") or ""), "scope": str(cap.get("scope") or ""),
            "dependencies": cap.get("dependencies", item.get("dependencies", [])),
            "validation_status": cap.get("validation_status", "unverified"),
            "reason": str(cap.get("reason") or ""),
            "runtime_reasons": cap.get("runtime_reasons", []),
        })
    available = [entry for entry in entries if entry["validation_status"] == "validated"]
    unavailable = [entry for entry in entries if entry["validation_status"] != "validated"]
    # Publish source behavior descriptions beside the implementation. Evidence
    # about tests, consumer counts or reviewer decisions stays in the audit.
    member_files = {origin["file"] for origin in origins}
    reference_notes = []
    for evidence in item.get("evidence", []):
        if not isinstance(evidence, dict) or evidence.get("file_id") not in member_files:
            continue
        claim = evidence.get("claim")
        if isinstance(claim, str) and claim.strip():
            note = {key: evidence[key] for key in ("file_id", "line_start", "line_end", "claim") if key in evidence}
            if note not in reference_notes:
                reference_notes.append(note)
    return {
        "bundle_id": bundle_id, "name": item.get("name"), "library": library,
        "source": origins, "capability": "; ".join(e["contract"] for e in available) or item.get("capability") or item.get("summary") or "",
        "available": available, "unavailable": unavailable,
        "dependencies": item.get("dependencies", []), "applicability": item.get("applicability", {}),
        "limitations": item.get("limitations", []),
        "reference_overview": item.get("capability") or item.get("summary") or "",
        "reference_notes": reference_notes, "relationships": item.get("relationships", []),
        "extra_metadata": {key: item[key] for key in ("type", "applicability", "integration_steps", "invariants", "variation_points") if key in item},
        "details_file": f"components/{bundle_id}/README.md", "audit_file": f"audit/{bundle_id}.json",
    }


def _inline(value: Any) -> str:
    """Keep names and purposes on one Markdown line."""
    text = " ".join(str(value or "").split())
    for character in "\\`*_{}[]<>|":
        text = text.replace(character, "\\" + character)
    return text


def index_line(card: dict[str, Any], max_chars: int) -> str:
    purpose = " ".join(str(card["capability"]).split())
    if max_chars:
        purpose = _short(purpose, max_chars)
    name = _inline(card.get("name") or card["bundle_id"])
    directory = f"components/{card['bundle_id']}/"
    return f"- [{name}]({card['details_file']}) — {_inline(purpose)} · `{directory}`"


def component_readme(card: dict[str, Any], *, guidance: Any = None) -> str:
    """Render existing consumer metadata beside its code, without a model call."""
    import re

    def block(text: str, language: str = "python") -> str:
        fence = "`" * max(3, max((len(run) + 1 for run in re.findall(r"`+", text)), default=3))
        return f"{fence}{language}\n{text.rstrip()}\n{fence}"

    def prose(value: Any, *, numbered: bool = False) -> list[str]:
        if value is None or value == "" or value == [] or value == {}:
            return []
        if isinstance(value, dict):
            result = []
            for key, item in value.items():
                children = prose(item)
                if not children:
                    continue
                label = {"conditions": "Applicable when", "non_applicability": "Adaptation boundaries"}.get(
                    key, str(key).replace("_", " ").capitalize())
                result.extend([f"**{_inline(label)}**", "", *children, ""])
            return result
        if isinstance(value, list):
            result = []
            for index, item in enumerate(value, 1):
                children = prose(item)
                if not children:
                    continue
                marker = f"{index}. " if numbered else "- "
                indent = " " * len(marker)
                result.append(marker + children[0])
                result.extend(indent + line if line else "" for line in children[1:])
            return result
        if isinstance(value, bool):
            return ["Yes" if value else "No"]
        return str(value).strip().splitlines()

    def section(title: str, value: Any, *, numbered: bool = False) -> None:
        content = prose(value, numbered=numbered)
        if content:
            lines.extend([f"## {title}", "", *content, ""])

    loading = (
        "import importlib.util\nimport sys\n\n"
        "sys.path.insert(0, '/testbed')\n"
        f"spec = importlib.util.spec_from_file_location('common', {str(COMPONENT_DIRECTORY + '/' + card['library'])!r})\n"
        "common = importlib.util.module_from_spec(spec)\n"
        "sys.modules['common'] = common\n"
        "spec.loader.exec_module(common)\n"
    )
    lines = [f"# {_inline(card.get('name') or card['bundle_id'])}", "",
             str(card["capability"]).strip(), "", "Implementation: [component.py](component.py)", "",
             "## Loading in the task repository", "",
             "Use the repository's Python environment. This makes /testbed available for repository imports "
             "and loads this file as common, matching its smoke cases.", "", block(loading), "",
             "Examples below use common as the loaded module. Component storage does not recreate the "
             "original package layout or relocate its resource files.", "",
             "## Source in the original repository", ""]
    for source in card["source"]:
        lines.append(f"- `{source.get('file')}`: `{source.get('symbol')}`")
    if not card["source"]:
        lines.append("Source location was not recorded.")
    lines.append("")
    for heading, entries in (("Validated paths", card["available"]),
                             ("Missing, failed or unverified paths", card["unavailable"])):
        if not entries:
            continue
        lines.extend([f"## {heading}", ""])
        for entry in entries:
            lines.extend([f"### {_inline(entry['path'])}", "", f"Status: {entry['validation_status']}", ""])
            if entry["signature"]:
                lines.extend([block(entry["signature"], "python"), ""])
            for label, field in (("Contract", "contract"), ("Scope", "scope"), ("Reason", "reason")):
                if entry[field]:
                    lines.extend([f"{label}: {entry[field]}", ""])
            if entry["example"]:
                lines.extend(["Example:", "", block(entry["example"], "python"), ""])
            if entry["dependencies"] and entry["dependencies"] != card["dependencies"]:
                lines.extend(["Dependencies:", "", *prose(entry["dependencies"]), ""])
    section("Dependencies", card["dependencies"])
    section("Applicability", card["applicability"])
    for field, title in (("integration_steps", "Integration"), ("invariants", "Invariants"),
                         ("variation_points", "Variation points")):
        section(title, card["extra_metadata"].get(field), numbered=field == "integration_steps")
    section("Limitations", card["limitations"])
    overview = card.get("reference_overview")
    if overview and overview != card["capability"]:
        section("Implementation reference", overview)
    section("Relationships and extension points", card.get("relationships"))
    if card.get("reference_notes"):
        lines.extend(["## Source implementation notes", ""])
        for note in card["reference_notes"]:
            location = str(note["file_id"])
            if "line_start" in note:
                location += f":{note['line_start']}"
                if "line_end" in note:
                    location += f"–{note['line_end']}"
            lines.extend([f"Source: `{location}`", "", note["claim"], ""])
    section("Guidance", guidance)
    lines.extend(["Smoke results cover the recorded paths and inputs.", "",
                  f"Review evidence: [audit JSON](../../{card['audit_file']})", ""])
    return "\n".join(lines)
