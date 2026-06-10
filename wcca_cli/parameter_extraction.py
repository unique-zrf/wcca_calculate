from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .docgen import extract_numeric_evidence
from .io import write_yaml
from .knowledge_providers import query_knowledge


def extract_parameter_candidates(
    project_dir: str | Path,
    input_document: dict[str, Any],
    knowledge_config: dict[str, Any] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    root = Path(project_dir)
    candidates: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for block in input_document.get("circuit_blocks", []):
        for query in _queries_for_block(block):
            try:
                hits = query_knowledge(query, knowledge_config, limit=limit)
                error = None
            except Exception as exc:
                hits = []
                error = str(exc)
            if error:
                evidence_rows.append({
                    "circuit_block_id": block.get("id"),
                    "query": query,
                    "provider": (knowledge_config or {"provider": "local"}).get("provider", "local"),
                    "title": "",
                    "source": "",
                    "score": "",
                    "parameter_hint": "",
                    "value": "",
                    "unit": "",
                    "review_status": "provider_error",
                    "risk_reason": error,
                    "evidence_excerpt": "",
                })
                continue
            for hit in hits:
                for numeric in extract_numeric_evidence(hit.content):
                    record = {
                        "circuit_block_id": block.get("id"),
                        "circuit_block_name": block.get("name"),
                        "query": query,
                        "parameter_hint": numeric.get("parameter_hint"),
                        "value": _parse_float(numeric.get("value")),
                        "unit": numeric.get("unit"),
                        "source": {
                            "type": "knowledge_provider",
                            "provider": hit.provider,
                            "title": hit.title,
                            "path": hit.source,
                            "score": hit.score,
                        },
                        "extraction_method": "knowledge_rule",
                        "review_status": "knowledge_extracted",
                        "risk_reason": "Candidate only; engineer confirmation required before release.",
                        "evidence_excerpt": numeric.get("evidence_excerpt"),
                    }
                    candidates.append(record)
                    evidence_rows.append({
                        "circuit_block_id": block.get("id"),
                        "query": query,
                        "provider": hit.provider,
                        "title": hit.title,
                        "source": hit.source,
                        "score": hit.score,
                        "parameter_hint": numeric.get("parameter_hint"),
                        "value": numeric.get("value"),
                        "unit": numeric.get("unit"),
                        "review_status": "knowledge_extracted",
                        "risk_reason": "Candidate only; engineer confirmation required before release.",
                        "evidence_excerpt": numeric.get("evidence_excerpt"),
                    })
    document = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "summary": {
            "candidate_count": len(candidates),
            "release_ready_count": 0,
            "review_required_count": len(candidates),
        },
        "candidates": candidates,
    }
    write_yaml(root / "work" / "extracted" / "parameter_candidates.yaml", document)
    _write_evidence_csv(root / "work" / "extracted" / "evidence_candidates.csv", evidence_rows)
    return document


def _queries_for_block(block: dict[str, Any]) -> list[str]:
    selected = block.get("selected_model", {})
    queries = []
    base_terms = [
        block.get("id"),
        block.get("name"),
        block.get("type"),
        selected.get("model_id"),
        selected.get("kb_card_id"),
    ]
    base_query = " ".join(str(term) for term in base_terms if term)
    if base_query:
        queries.append(base_query)
    for path, record in _parameter_records(block.get("inputs", {})):
        source = record.get("source") if isinstance(record, dict) else {}
        document_id = source.get("document_id") if isinstance(source, dict) else None
        parts = [document_id, path, record.get("parameter_type"), record.get("unit")]
        query = " ".join(str(part) for part in parts if part)
        if query:
            queries.append(query)
    return list(dict.fromkeys(queries))


def _parameter_records(node: Any, prefix: str = "") -> list[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict) and "value" in node:
        return [(prefix, node)]
    records: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            records.extend(_parameter_records(value, child_prefix))
    return records


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_evidence_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "circuit_block_id",
        "query",
        "provider",
        "title",
        "source",
        "score",
        "parameter_hint",
        "value",
        "unit",
        "review_status",
        "risk_reason",
        "evidence_excerpt",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
