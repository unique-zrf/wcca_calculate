from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .knowledge_providers import KnowledgeHit, query_knowledge


def build_document_package(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
    output_dir: str | Path,
    knowledge_config: dict[str, Any] | None = None,
    citation_limit: int = 3,
    input_path: str | Path | None = None,
    results_path: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    context = _collect_knowledge_context(input_document, results_document, knowledge_config, citation_limit)
    document_path = _write_document(target / "wcca_document.md", input_document, results_document, context)
    references_path = _write_references(target / "source_references.md", context)
    traceability_path = _write_traceability_matrix(target / "traceability_matrix.csv", input_document, results_document)
    evidence_path = _write_evidence_candidates(target / "evidence_candidates.csv", context)
    generated_files = [document_path, references_path, traceability_path, evidence_path]
    manifest = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "document": str(document_path),
        "source_references": str(references_path),
        "traceability_matrix": str(traceability_path),
        "evidence_candidates": str(evidence_path),
        "knowledge_provider": (knowledge_config or {"provider": "local"}).get("provider", "local"),
        "citation_count": sum(len(item["hits"]) for item in context),
        "input_sha256": _file_sha256(input_path) if input_path else None,
        "results_sha256": _file_sha256(results_path) if results_path else None,
        "files": [
            {"path": str(path), "sha256": _file_sha256(path)}
            for path in generated_files
        ],
    }
    write_json(target / "docgen_manifest.json", manifest)
    return manifest


DOCUMENT_PACKAGE_FILES = [
    "output/document/wcca_document.md",
    "output/document/source_references.md",
    "output/document/traceability_matrix.csv",
    "output/document/evidence_candidates.csv",
    "output/document/docgen_manifest.json",
]


def validate_document_package(project_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(project_dir)
    issues: list[dict[str, Any]] = []
    document_dir = root / "output" / "document"
    manifest_path = document_dir / "docgen_manifest.json"
    input_path = root / "work" / "wcca_input.yaml"
    results_path = root / "output" / "calculation" / "results.json"
    references_path = document_dir / "source_references.md"
    traceability_path = document_dir / "traceability_matrix.csv"
    document_path = document_dir / "wcca_document.md"

    for rel_path in DOCUMENT_PACKAGE_FILES:
        if not (root / rel_path).exists():
            issues.append({"level": "error", "path": rel_path, "message": "Required document package file is missing"})
    if not manifest_path.exists():
        return issues

    try:
        manifest = read_json(manifest_path)
    except Exception as exc:
        return [{"level": "error", "path": str(manifest_path), "message": f"Invalid document manifest: {exc}"}]

    _audit_manifest_input_hash(manifest, input_path, "input_sha256", issues)
    _audit_manifest_input_hash(manifest, results_path, "results_sha256", issues)
    _audit_manifest_file_hashes(manifest, root, issues)

    if results_path.exists() and traceability_path.exists():
        _audit_document_traceability(traceability_path, read_json(results_path), issues)
    if results_path.exists() and references_path.exists():
        _audit_source_reference_coverage(references_path, read_json(results_path), issues)
    if document_path.exists():
        _audit_document_text(document_path, read_json(results_path) if results_path.exists() else {}, issues)
    return issues


def _audit_manifest_input_hash(
    manifest: dict[str, Any],
    path: Path,
    field: str,
    issues: list[dict[str, Any]],
) -> None:
    if not path.exists():
        return
    expected = _file_sha256(path)
    actual = manifest.get(field)
    if actual != expected:
        issues.append({
            "level": "error",
            "path": f"output/document/docgen_manifest.json:{field}",
            "message": f"Expected {expected}, got {actual}",
        })


def _audit_manifest_file_hashes(manifest: dict[str, Any], root: Path, issues: list[dict[str, Any]]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list):
        issues.append({"level": "error", "path": "output/document/docgen_manifest.json:files", "message": "files must be a list"})
        return
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            issues.append({"level": "error", "path": f"output/document/docgen_manifest.json:files[{index}]", "message": "file entry must be a mapping"})
            continue
        path_text = item.get("path")
        expected_hash = item.get("sha256")
        if not path_text or not expected_hash:
            issues.append({"level": "error", "path": f"output/document/docgen_manifest.json:files[{index}]", "message": "file entry needs path and sha256"})
            continue
        path = _resolve_manifest_path(path_text, root)
        if not path.exists():
            issues.append({"level": "error", "path": str(path), "message": "Manifest file path is missing"})
            continue
        actual_hash = _file_sha256(path)
        if actual_hash != expected_hash:
            issues.append({
                "level": "error",
                "path": str(path),
                "message": f"Document file hash mismatch: expected {expected_hash}, got {actual_hash}",
            })


def _audit_document_traceability(
    traceability_path: Path,
    results_document: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    with traceability_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual = {
        (row.get("requirement_id"), row.get("circuit_block_id")): row
        for row in rows
    }
    expected = {
        (row.get("requirement_id"), row.get("circuit_block_id")): row
        for row in results_document.get("requirements_coverage", [])
    }
    result_by_block = {
        row.get("circuit_block_id"): row
        for row in results_document.get("results", [])
    }
    for key, expected_row in expected.items():
        actual_row = actual.get(key)
        if actual_row is None:
            issues.append({"level": "error", "path": str(traceability_path), "message": f"Traceability matrix missing row {key}"})
            continue
        summary = result_by_block.get(key[1], {}).get("summary_result", {})
        expected_values = {
            **expected_row,
            "margin_min": summary.get("margin_min"),
            "margin_max": summary.get("margin_max"),
        }
        for field in ("model_id", "model_version", "pass_fail", "margin_min", "margin_max"):
            if _csv_value_mismatch(actual_row.get(field), expected_values.get(field)):
                issues.append({
                    "level": "error",
                    "path": str(traceability_path),
                    "message": f"Traceability {key} field {field} should be {expected_values.get(field)}, got {actual_row.get(field)}",
                })
    for key in sorted(set(actual) - set(expected)):
        issues.append({"level": "error", "path": str(traceability_path), "message": f"Traceability matrix has unexpected row {key}"})


def _audit_source_reference_coverage(
    references_path: Path,
    results_document: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    references_text = references_path.read_text(encoding="utf-8")
    document_ids = {
        row.get("document_id")
        for row in results_document.get("parameter_sources", [])
        if row.get("document_id")
    }
    for document_id in sorted(document_ids):
        if document_id not in references_text:
            issues.append({
                "level": "error",
                "path": str(references_path),
                "message": f"Source references missing document_id {document_id}",
            })


def _audit_document_text(document_path: Path, results_document: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    text = document_path.read_text(encoding="utf-8")
    for risk_word in ("TBD", "To Be Confirmed", "TODO"):
        if risk_word.lower() in text.lower():
            issues.append({"level": "warning", "path": str(document_path), "message": f"Document contains risk word: {risk_word}"})
    statuses = [item.get("summary_result", {}).get("pass_fail") for item in results_document.get("results", [])]
    if statuses and all(status == "pass" for status in statuses) and "All calculated circuit blocks pass" not in text:
        issues.append({"level": "error", "path": str(document_path), "message": "Document conclusion does not match passing calculation results"})
    if any(status == "fail" for status in statuses) and "At least one calculated circuit block fails" not in text:
        issues.append({"level": "error", "path": str(document_path), "message": "Document conclusion does not match failing calculation results"})


def _resolve_manifest_path(path_text: str, root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute() or path.exists():
        return path
    return root / path


def _csv_value_mismatch(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual not in (None, "")
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) > 1e-9
        except (TypeError, ValueError):
            return True
    return str(actual) != str(expected)


def _collect_knowledge_context(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
    knowledge_config: dict[str, Any] | None,
    limit: int,
) -> list[dict[str, Any]]:
    queries = _knowledge_queries(input_document, results_document)
    context = []
    for query in queries:
        try:
            hits = query_knowledge(query, knowledge_config, limit=limit)
            error = None
        except Exception as exc:
            hits = []
            error = str(exc)
        context.append({"query": query, "hits": hits, "error": error})
    return context


def _knowledge_queries(input_document: dict[str, Any], results_document: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    for block in input_document.get("circuit_blocks", []):
        selected = block.get("selected_model", {})
        terms = [
            block.get("id"),
            block.get("name"),
            block.get("type"),
            selected.get("model_id"),
            selected.get("kb_card_id"),
        ]
        query = " ".join(str(term) for term in terms if term)
        if query:
            queries.append(query)
    for row in results_document.get("parameter_sources", []):
        document_id = row.get("document_id")
        if document_id and document_id not in queries:
            queries.append(str(document_id))
    return list(dict.fromkeys(queries))[:20]


def _write_document(
    path: Path,
    input_document: dict[str, Any],
    results_document: dict[str, Any],
    context: list[dict[str, Any]],
) -> Path:
    project = input_document.get("project", {})
    lines = [
        f"# {project.get('name', 'WCCA Project')} WCCA Document",
        "",
        "## Document Information",
        "",
        f"- Document type: {project.get('document_type', 'WCCA')}",
        f"- Generated at: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        f"- Calculation status: {results_document.get('status')}",
        f"- Release status: {results_document.get('release_status')}",
        "",
        "## Analysis Scope",
        "",
    ]
    for block in input_document.get("circuit_blocks", []):
        lines.append(f"- {block.get('id')}: {block.get('name', '')} ({block.get('type', '')})")
    lines.extend([
        "",
        "## Design Requirements",
        "",
        "| Requirement ID | Circuit Block | Min | Max | Unit | Source | Review Status |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ])
    for block in input_document.get("circuit_blocks", []):
        for requirement in block.get("requirements", []):
            source = requirement.get("source") or {}
            lines.append(
                f"| {requirement.get('id')} | {block.get('id')} | {requirement.get('min_value')} | "
                f"{requirement.get('max_value')} | {requirement.get('unit', '')} | "
                f"{source.get('document_id', source.get('path', ''))} | {requirement.get('review_status', '')} |"
            )
    lines.extend([
        "",
        "## Analysis Method",
        "",
        "All critical numerical results in this document are populated from deterministic WCCA calculation outputs. "
        "Knowledge-base results are used as evidence and context only, and engineering sign-off remains mandatory.",
        "",
        "## Calculation Results",
        "",
        "| Circuit Block | Model | Worst Min | Worst Max | Requirement | Margin Min | Margin Max | Result |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | --- |",
    ])
    for result in results_document.get("results", []):
        summary = result.get("summary_result", {})
        lines.append(
            f"| {result.get('circuit_block_id')} | {result.get('model_id')} {result.get('model_version')} | "
            f"{summary.get('worst_min')} | {summary.get('worst_max')} | "
            f"{summary.get('requirement_min')} to {summary.get('requirement_max')} | "
            f"{summary.get('margin_min')} | {summary.get('margin_max')} | {summary.get('pass_fail')} |"
        )
    lines.extend([
        "",
        "## Parameter Sources",
        "",
        "| Circuit Block | Parameter | Value | Unit | Type | Source | Review Status | Risk Reason |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- |",
    ])
    for row in results_document.get("parameter_sources", []):
        lines.append(
            f"| {row.get('circuit_block_id')} | {row.get('parameter')} | {row.get('value')} | {row.get('unit')} | "
            f"{row.get('parameter_type')} | {row.get('document_id', '')} {row.get('source_detail', '')} | "
            f"{row.get('review_status', '')} | {row.get('risk_reason', '')} |"
        )
    lines.extend(_risk_section(results_document))
    lines.extend(_knowledge_section(context))
    lines.extend([
        "",
        "## Conclusion",
        "",
        _conclusion(results_document),
        "",
        "## Sign-Off",
        "",
        "- Hardware engineer review: Pending",
        "- Quality/reliability review: Pending",
        "- Final decision: Pending",
        "",
        "## Appendix",
        "",
        "- Calculation workbook: `output/calculation/wcca_results.xlsx`",
        "- Parameter source matrix: `output/calculation/parameter_sources.csv`",
        "- Requirements coverage matrix: `output/calculation/requirements_coverage.csv`",
        "- Model trace: `output/calculation/model_trace.json`",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _risk_section(results_document: dict[str, Any]) -> list[str]:
    lines = ["", "## Risk Items", ""]
    risks = results_document.get("risk_items", [])
    if not risks:
        lines.append("- No risk items reported by calculation output.")
        return lines
    for risk in risks:
        lines.append(
            f"- {risk.get('risk_type')}: {risk.get('circuit_block_id')} "
            f"{risk.get('parameter', '')} {risk.get('message', risk.get('risk_reason', ''))}"
        )
    return lines


def _knowledge_section(context: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Knowledge-Base Evidence", ""]
    if not context:
        lines.append("- No knowledge-base query was requested.")
        return lines
    for item in context:
        lines.append(f"### Query: {item['query']}")
        if item.get("error"):
            lines.append(f"- Provider error: {item['error']}")
            lines.append("")
            continue
        hits: list[KnowledgeHit] = item.get("hits", [])
        if not hits:
            lines.append("- No matching evidence returned.")
            lines.append("")
            continue
        for hit in hits:
            excerpt = " ".join(hit.content.split())[:300]
            lines.append(f"- [{hit.provider}] {hit.title} ({hit.source}): {excerpt}")
        lines.append("")
    return lines


def _conclusion(results_document: dict[str, Any]) -> str:
    statuses = [
        item.get("summary_result", {}).get("pass_fail")
        for item in results_document.get("results", [])
    ]
    if statuses and all(status == "pass" for status in statuses):
        return "All calculated circuit blocks pass their linked requirements based on the current approved inputs."
    if any(status == "fail" for status in statuses):
        return "At least one calculated circuit block fails its linked requirement. Engineering review is required before release."
    return "No final pass/fail conclusion is available from the calculation output."


def _write_references(path: Path, context: list[dict[str, Any]]) -> Path:
    lines = ["# Source References", ""]
    for item in context:
        lines.append(f"## {item['query']}")
        if item.get("error"):
            lines.append(f"- Provider error: {item['error']}")
            continue
        for hit in item.get("hits", []):
            lines.append(f"- {hit.provider}: {hit.title}; source={hit.source}; score={hit.score}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_traceability_matrix(path: Path, input_document: dict[str, Any], results_document: dict[str, Any]) -> Path:
    result_by_block = {item.get("circuit_block_id"): item for item in results_document.get("results", [])}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "requirement_id",
            "circuit_block_id",
            "model_id",
            "model_version",
            "pass_fail",
            "margin_min",
            "margin_max",
            "source_document_id",
            "review_status",
        ])
        writer.writeheader()
        for block in input_document.get("circuit_blocks", []):
            result = result_by_block.get(block.get("id"), {})
            summary = result.get("summary_result", {})
            selected = block.get("selected_model", {})
            for requirement in block.get("requirements", []):
                source = requirement.get("source") or {}
                writer.writerow({
                    "requirement_id": requirement.get("id"),
                    "circuit_block_id": block.get("id"),
                    "model_id": selected.get("model_id"),
                    "model_version": selected.get("model_version"),
                    "pass_fail": summary.get("pass_fail"),
                    "margin_min": summary.get("margin_min"),
                    "margin_max": summary.get("margin_max"),
                    "source_document_id": source.get("document_id"),
                    "review_status": requirement.get("review_status"),
                })
    return path


def _write_evidence_candidates(path: Path, context: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "query",
            "provider",
            "title",
            "source",
            "score",
            "parameter_hint",
            "value",
            "unit",
            "evidence_excerpt",
        ])
        writer.writeheader()
        for item in context:
            query = item.get("query", "")
            for hit in item.get("hits", []):
                for candidate in extract_numeric_evidence(hit.content):
                    writer.writerow({
                        "query": query,
                        "provider": hit.provider,
                        "title": hit.title,
                        "source": hit.source,
                        "score": hit.score,
                        **candidate,
                    })
    return path


def extract_numeric_evidence(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    compact = " ".join(text.split())
    pattern = re.compile(
        r"(?P<label>[A-Za-z_][A-Za-z0-9_\-/ ]{0,40})?"
        r"(?P<value>[-+]?\d+(?:\.\d+)?)\s*"
        r"(?P<unit>%|ppm|mV|V|uV|A|mA|uA|ohm|kohm|Mohm|F|uF|nF|pF|s|ms|us|C)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(compact):
        unit = match.group("unit")
        label = (match.group("label") or "").strip(" :-,;")
        start, end = match.span()
        excerpt = compact[max(0, start - 80): min(len(compact), end + 120)]
        if not unit and not _looks_like_engineering_label(label):
            continue
        candidates.append({
            "parameter_hint": label,
            "value": match.group("value"),
            "unit": unit or "",
            "evidence_excerpt": excerpt,
        })
        if len(candidates) >= 20:
            break
    return candidates


def _looks_like_engineering_label(label: str) -> bool:
    lowered = label.lower()
    keywords = [
        "min",
        "max",
        "typ",
        "tolerance",
        "tempco",
        "aging",
        "accuracy",
        "voltage",
        "current",
        "resistance",
        "capacitance",
    ]
    return any(keyword in lowered for keyword in keywords)


def _file_sha256(path: str | Path | None) -> str | None:
    if path is None:
        return None
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
