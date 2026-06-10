from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .io import read_yaml
from .registry import ROOT, ModelRef, file_sha256, iter_models


def validate_knowledge_cards() -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for model in iter_models():
        issues.extend(validate_model_assets(model))
        issues.extend(validate_model_card_binding(model))
    issues.extend(_validate_document_index())
    return issues


def validate_model_assets(model: ModelRef) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    required_files = [
        "model.yaml",
        "implementation.py",
        "formula.md",
        "review_record.md",
    ]
    for rel_path in required_files:
        path = model.path / rel_path
        if not path.exists():
            issues.append({"level": "error", "path": str(path), "message": f"Missing model asset: {rel_path}"})

    examples = sorted((model.path / "examples").glob("*.yaml")) if (model.path / "examples").exists() else []
    if len(examples) < 3:
        issues.append({
            "level": "error",
            "path": str(model.path / "examples"),
            "message": f"Model requires at least 3 example YAML files, found {len(examples)}",
        })

    tests = sorted((model.path / "tests").glob("test_*.py")) if (model.path / "tests").exists() else []
    if not tests:
        issues.append({
            "level": "error",
            "path": str(model.path / "tests"),
            "message": "Model requires at least one test_*.py file",
        })
    else:
        test_count = sum(_count_test_functions(path) for path in tests)
        if test_count < 10:
            issues.append({
                "level": "error",
                "path": str(model.path / "tests"),
                "message": f"Model requires at least 10 test cases, found {test_count}",
            })

    for field in ("model_id", "version", "status", "kb_card_id"):
        if not model.metadata.get(field):
            issues.append({
                "level": "error",
                "path": str(model.path / "model.yaml"),
                "message": f"Missing model metadata field: {field}",
            })
    return issues


def _count_test_functions(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    )


def validate_model_card_binding(model: ModelRef) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    kb_card_id = model.metadata.get("kb_card_id")
    card_path = ROOT / "wcca_knowledge_base" / "model_cards" / f"{kb_card_id}.yaml"
    if not kb_card_id:
        return [{"level": "error", "path": str(model.path / "model.yaml"), "message": "Missing kb_card_id"}]
    if not card_path.exists():
        return [{"level": "error", "path": str(card_path), "message": "Missing model card"}]

    card = read_yaml(card_path)
    _expect_equal(issues, card_path, "model_id", card.get("model_id"), model.model_id)
    _expect_equal(issues, card_path, "model_version", card.get("model_version"), model.version)
    _expect_equal(issues, card_path, "status", card.get("status"), model.metadata.get("status"))
    _expect_equal(issues, card_path, "kb_card_id", card.get("kb_card_id"), kb_card_id)
    _expect_list_equal(
        issues,
        card_path,
        "applicable_circuits",
        card.get("applicable_circuits", []),
        model.metadata.get("circuit_types", []),
    )
    _expect_list_equal(
        issues,
        card_path,
        "required_parameters",
        card.get("required_parameters", []),
        _required_parameter_paths(model.metadata),
    )
    _expect_list_equal(
        issues,
        card_path,
        "outputs",
        card.get("outputs", []),
        _output_names(model.metadata),
    )

    for index, source_file in enumerate(card.get("source_files", [])):
        rel_path = source_file.get("path")
        if not rel_path:
            issues.append({
                "level": "error",
                "path": f"{card_path}:source_files[{index}]",
                "message": "Missing source file path",
            })
            continue
        if rel_path.endswith("implementation.py"):
            issues.append({
                "level": "error",
                "path": rel_path,
                "message": "Knowledge card must not index executable model code",
            })
        source_path = ROOT / rel_path
        if not source_path.exists():
            issues.append({"level": "error", "path": rel_path, "message": "Source file does not exist"})
            continue
        expected_hash = source_file.get("sha256")
        actual_hash = file_sha256(source_path)
        if expected_hash != actual_hash:
            issues.append({
                "level": "error",
                "path": rel_path,
                "message": f"sha256 mismatch: expected {expected_hash}, got {actual_hash}",
            })
    return issues


def _required_parameter_paths(model_metadata: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in model_metadata.get("inputs", []):
        if not item.get("required", False):
            continue
        name = item.get("name")
        if not name:
            continue
        fields = item.get("fields")
        if fields:
            paths.extend(f"{name}.{field}" for field in fields)
        else:
            paths.append(name)
    return paths


def _output_names(model_metadata: dict[str, Any]) -> list[str]:
    return [
        item["name"]
        for item in model_metadata.get("outputs", [])
        if item.get("name")
    ]


def _validate_document_index() -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    index_path = ROOT / "wcca_knowledge_base" / "index" / "documents_index.yaml"
    if not index_path.exists():
        issues.append({"level": "error", "path": str(index_path), "message": "Missing documents index"})
        return issues

    seen_ids: set[str] = set()
    data = read_yaml(index_path)
    for index, document in enumerate(data.get("documents", [])):
        path = f"{index_path}:documents[{index}]"
        document_id = document.get("document_id")
        if not document_id:
            issues.append({"level": "error", "path": path, "message": "Missing document_id"})
        elif document_id in seen_ids:
            issues.append({"level": "error", "path": path, "message": f"Duplicate document_id: {document_id}"})
        else:
            seen_ids.add(document_id)

        if not document.get("doc_type"):
            issues.append({"level": "error", "path": path, "message": "Missing doc_type"})
        if not document.get("title"):
            issues.append({"level": "error", "path": path, "message": "Missing title"})

        rel_path = document.get("path")
        if not rel_path:
            issues.append({"level": "error", "path": path, "message": "Missing path"})
        elif not (ROOT / rel_path).exists():
            issues.append({"level": "error", "path": rel_path, "message": "Indexed document path does not exist"})
    return issues


def search_knowledge(query: str, limit: int = 10) -> list[dict[str, Any]]:
    normalized_query = query.strip().lower()
    terms = [term.lower() for term in query.split() if term.strip()]
    records = _knowledge_records()
    exact_matches = []
    if normalized_query:
        for record in records:
            exact_terms = {term.lower() for term in record.get("exact_terms", []) if term}
            if normalized_query in exact_terms:
                result = _public_record(record)
                result["score"] = 1000
                exact_matches.append(result)
    if exact_matches:
        exact_matches.sort(key=lambda item: (item["doc_type"], item["id"]))
        return exact_matches[:limit]

    scored = []
    for record in records:
        haystack = record["search_text"].lower()
        score = sum(haystack.count(term) for term in terms) if terms else 1
        if score > 0:
            result = _public_record(record)
            result["score"] = score
            scored.append(result)
    scored.sort(key=lambda item: (-item["score"], item["doc_type"], item["id"]))
    return scored[:limit]


def show_knowledge(identifier: str) -> dict[str, Any] | None:
    for record in _knowledge_records():
        if identifier in {record["id"], record["path"]}:
            return _public_record(record)
    return None


def _knowledge_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(_model_card_records())
    records.extend(_document_records())
    records.extend(_parameter_rule_records())
    records.extend(_review_note_records())
    return records


def _document_records() -> list[dict[str, Any]]:
    path = ROOT / "wcca_knowledge_base" / "index" / "documents_index.yaml"
    if not path.exists():
        return []
    data = read_yaml(path)
    records = []
    for document in data.get("documents", []):
        document_id = document.get("document_id")
        title = document.get("title") or document_id
        summary_parts = [
            document_id or "",
            document.get("doc_type", ""),
            title or "",
            document.get("summary", ""),
            " ".join(document.get("part_numbers", [])),
            " ".join(document.get("keywords", [])),
        ]
        records.append({
            "id": document_id,
            "doc_type": document.get("doc_type", "document"),
            "title": title,
            "path": document.get("path", _rel(path)),
            "summary": "; ".join(part for part in summary_parts if part),
            "data": document,
            "exact_terms": _exact_terms(
                document_id,
                document.get("path"),
                document.get("part_numbers", []),
            ),
            "search_text": json.dumps(document, ensure_ascii=False),
        })
    return records


def _model_card_records() -> list[dict[str, Any]]:
    records = []
    for path in sorted((ROOT / "wcca_knowledge_base" / "model_cards").glob("*.yaml")):
        card = read_yaml(path)
        summary_parts = [
            card.get("kb_card_id", ""),
            card.get("model_id", ""),
            str(card.get("model_version", "")),
            card.get("status", ""),
            " ".join(card.get("applicable_circuits", [])),
            " ".join(card.get("required_parameters", [])),
            " ".join(card.get("limitations", [])),
        ]
        records.append({
            "id": card.get("kb_card_id"),
            "doc_type": card.get("doc_type", "calculation_model_card"),
            "title": f"{card.get('model_id')} {card.get('model_version')}",
            "path": _rel(path),
            "summary": "; ".join(part for part in summary_parts if part),
            "data": card,
            "exact_terms": _exact_terms(
                card.get("kb_card_id"),
                card.get("model_id"),
                f"{card.get('model_id')}:{card.get('model_version')}",
                path.name,
            ),
            "search_text": json.dumps(card, ensure_ascii=False),
        })
    return records


def _parameter_rule_records() -> list[dict[str, Any]]:
    path = ROOT / "wcca_knowledge_base" / "index" / "parameter_rules_index.yaml"
    if not path.exists():
        return []
    data = read_yaml(path)
    records = []
    for rule in data.get("parameter_rules", []):
        records.append({
            "id": rule.get("id"),
            "doc_type": "parameter_rule",
            "title": rule.get("id"),
            "path": _rel(path),
            "summary": rule.get("description", ""),
            "data": rule,
            "exact_terms": _exact_terms(rule.get("id")),
            "search_text": json.dumps(rule, ensure_ascii=False),
        })
    return records


def _review_note_records() -> list[dict[str, Any]]:
    records = []
    for path in sorted((ROOT / "wcca_knowledge_base" / "review_notes").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text.splitlines() else path.stem
        records.append({
            "id": f"REVIEW-NOTE-{path.stem}",
            "doc_type": "review_note",
            "title": title,
            "path": _rel(path),
            "summary": " ".join(line.strip("- ") for line in text.splitlines()[1:6] if line.strip()),
            "data": {"text": text},
            "exact_terms": _exact_terms(f"REVIEW-NOTE-{path.stem}", path.name),
            "search_text": text,
        })
    return records


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in {"search_text", "exact_terms"}}


def _exact_terms(*values: Any) -> list[str]:
    terms: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            terms.extend(_exact_terms(*value))
            continue
        text = str(value).strip()
        if text:
            terms.append(text)
    return terms


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _expect_equal(
    issues: list[dict[str, Any]],
    card_path: Path,
    field: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        issues.append({
            "level": "error",
            "path": f"{card_path}:{field}",
            "message": f"Expected {expected}, got {actual}",
        })


def _expect_list_equal(
    issues: list[dict[str, Any]],
    card_path: Path,
    field: str,
    actual: Any,
    expected: list[str],
) -> None:
    actual_list = list(actual or []) if isinstance(actual, list) else actual
    if actual_list != expected:
        issues.append({
            "level": "error",
            "path": f"{card_path}:{field}",
            "message": f"Expected {expected}, got {actual_list}",
        })
