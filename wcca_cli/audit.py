from __future__ import annotations

import hashlib
import csv
import json
import zipfile
from pathlib import Path
from typing import Any

from .io import read_json, read_yaml
from .registry import file_sha256, get_model
from .reporting import validate_results
from .validation import has_errors, validate_input_document


REQUIRED_PROJECT_FILES = [
    "work/wcca_input.yaml",
    "output/calculation/results.json",
    "output/calculation/model_trace.json",
    "output/calculation/risk_items.md",
    "output/calculation/parameter_sources.csv",
    "output/calculation/requirements_coverage.csv",
    "output/report/wcca_report.md",
    "review/comments/review_checklist.json",
    "review/approvals/approval_record.json",
]


def audit_project(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    issues: list[dict[str, Any]] = []
    _audit_required_files(root, issues)

    input_path = root / "work" / "wcca_input.yaml"
    results_path = root / "output" / "calculation" / "results.json"
    trace_path = root / "output" / "calculation" / "model_trace.json"
    parameter_sources_path = root / "output" / "calculation" / "parameter_sources.csv"
    coverage_path = root / "output" / "calculation" / "requirements_coverage.csv"
    approval_path = root / "review" / "approvals" / "approval_record.json"
    package_path = root / "release" / "wcca_package.zip"

    input_document = read_yaml(input_path) if input_path.exists() else {}
    results_document = read_json(results_path) if results_path.exists() else {}
    trace_document = read_json(trace_path) if trace_path.exists() else {}

    if input_document:
        _extend_issues(issues, validate_input_document(input_document, release=True), "input")
    if input_document and results_document:
        _extend_issues(issues, validate_results(input_document, results_document), "results")
    if input_path.exists() and trace_document:
        _audit_traceability(input_path, trace_document, issues)
    if results_document and trace_document:
        _audit_trace_matches_results(trace_document, results_document, issues)
    if parameter_sources_path.exists() and results_document:
        _audit_parameter_sources_csv(parameter_sources_path, results_document, issues)
    if coverage_path.exists() and results_document:
        _audit_requirements_coverage_csv(coverage_path, results_document, issues)
    if approval_path.exists():
        _audit_approval(input_path, results_path, approval_path, issues)
    if package_path.exists():
        _audit_package(package_path, REQUIRED_PROJECT_FILES, issues)
    else:
        issues.append({"level": "error", "path": str(package_path), "message": "Missing release package"})

    return {
        "status": "failed" if has_errors(issues) else "passed",
        "issues": issues,
        "summary": {
            "issue_count": len(issues),
            "error_count": sum(1 for item in issues if item.get("level") == "error"),
            "warning_count": sum(1 for item in issues if item.get("level") == "warning"),
        },
    }


def _audit_required_files(root: Path, issues: list[dict[str, Any]]) -> None:
    for rel_path in REQUIRED_PROJECT_FILES:
        path = root / rel_path
        if not path.exists():
            issues.append({"level": "error", "path": rel_path, "message": "Required project file is missing"})


def _audit_traceability(input_path: Path, trace_document: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    expected_input_hash = f"sha256:{file_sha256(input_path)}"
    for item in trace_document.get("results", []):
        model_id = item.get("model_id")
        model_version = item.get("model_version")
        trace = item.get("traceability", {})
        if trace.get("input_version") != expected_input_hash:
            issues.append({
                "level": "error",
                "path": f"trace.{item.get('circuit_block_id')}.input_version",
                "message": f"Expected {expected_input_hash}, got {trace.get('input_version')}",
            })
        try:
            model = get_model(model_id, model_version)
        except KeyError as exc:
            issues.append({"level": "error", "path": f"trace.{model_id}", "message": str(exc)})
            continue
        expected_model_hash = f"sha256:{file_sha256(model.path / 'model.yaml')}"
        expected_impl_hash = f"sha256:{file_sha256(model.path / 'implementation.py')}"
        if trace.get("model_hash") != expected_model_hash:
            issues.append({
                "level": "error",
                "path": f"trace.{item.get('circuit_block_id')}.model_hash",
                "message": f"Expected {expected_model_hash}, got {trace.get('model_hash')}",
            })
        if trace.get("implementation_hash") != expected_impl_hash:
            issues.append({
                "level": "error",
                "path": f"trace.{item.get('circuit_block_id')}.implementation_hash",
                "message": f"Expected {expected_impl_hash}, got {trace.get('implementation_hash')}",
            })


def _audit_trace_matches_results(
    trace_document: dict[str, Any],
    results_document: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    trace_rows = {
        item.get("circuit_block_id"): item
        for item in trace_document.get("results", [])
    }
    result_rows = {
        item.get("circuit_block_id"): item
        for item in results_document.get("results", [])
    }
    for block_id, result_item in result_rows.items():
        trace_item = trace_rows.get(block_id)
        if trace_item is None:
            issues.append({
                "level": "error",
                "path": "output/calculation/model_trace.json",
                "message": f"Trace file missing result for {block_id}",
            })
            continue
        for field in ("model_id", "model_version", "model_status", "release_status"):
            if trace_item.get(field) != result_item.get(field):
                issues.append({
                    "level": "error",
                    "path": f"output/calculation/model_trace.json:{block_id}.{field}",
                    "message": f"Trace {field} should be {result_item.get(field)}, got {trace_item.get(field)}",
                })
        if trace_item.get("traceability") != result_item.get("traceability"):
            issues.append({
                "level": "error",
                "path": f"output/calculation/model_trace.json:{block_id}.traceability",
                "message": "Traceability does not match results.json",
            })
    for block_id in sorted(set(trace_rows) - set(result_rows)):
        issues.append({
            "level": "error",
            "path": "output/calculation/model_trace.json",
            "message": f"Trace file has unexpected result for {block_id}",
        })


def _audit_approval(input_path: Path, results_path: Path, approval_path: Path, issues: list[dict[str, Any]]) -> None:
    approval = read_json(approval_path)
    if approval.get("decision") != "approved":
        issues.append({"level": "warning", "path": str(approval_path), "message": f"Decision is {approval.get('decision')}"})
    if approval.get("validation_status") != "passed":
        issues.append({"level": "error", "path": str(approval_path), "message": "Approval validation_status is not passed"})
    if input_path.exists() and approval.get("input_sha256") != file_sha256(input_path):
        issues.append({
            "level": "error",
            "path": f"{approval_path}:input_sha256",
            "message": "Approval input hash does not match current input",
        })
    if results_path.exists() and approval.get("results_sha256") != file_sha256(results_path):
        issues.append({
            "level": "error",
            "path": f"{approval_path}:results_sha256",
            "message": "Approval results hash does not match current results",
        })


def _audit_requirements_coverage_csv(
    coverage_path: Path,
    results_document: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    with coverage_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual = {
        (row.get("requirement_id"), row.get("circuit_block_id")): row
        for row in rows
    }
    expected = {
        (row.get("requirement_id"), row.get("circuit_block_id")): row
        for row in results_document.get("requirements_coverage", [])
    }
    for key, expected_row in expected.items():
        actual_row = actual.get(key)
        if actual_row is None:
            issues.append({
                "level": "error",
                "path": str(coverage_path),
                "message": f"Coverage CSV missing row {key}",
            })
            continue
        for field, expected_value in expected_row.items():
            if _csv_value_mismatch(actual_row.get(field), expected_value):
                issues.append({
                    "level": "error",
                    "path": str(coverage_path),
                    "message": f"Coverage CSV {key} field {field} should be {expected_value}, got {actual_row.get(field)}",
                })
    for key in sorted(set(actual) - set(expected)):
        issues.append({
            "level": "error",
            "path": str(coverage_path),
            "message": f"Coverage CSV has unexpected row {key}",
        })


def _csv_value_mismatch(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual not in (None, "")
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) > 1e-9
        except (TypeError, ValueError):
            return True
    return str(actual) != str(expected)


def _audit_parameter_sources_csv(
    parameter_sources_path: Path,
    results_document: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    with parameter_sources_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    actual = {
        (row.get("circuit_block_id"), row.get("parameter")): row
        for row in rows
    }
    expected = {
        (row.get("circuit_block_id"), row.get("parameter")): row
        for row in results_document.get("parameter_sources", [])
    }
    for key, expected_row in expected.items():
        actual_row = actual.get(key)
        if actual_row is None:
            issues.append({
                "level": "error",
                "path": str(parameter_sources_path),
                "message": f"Parameter sources CSV missing row {key}",
            })
            continue
        for field, expected_value in expected_row.items():
            if _csv_value_mismatch(actual_row.get(field), expected_value):
                issues.append({
                    "level": "error",
                    "path": str(parameter_sources_path),
                    "message": f"Parameter sources CSV {key} field {field} should be {expected_value}, got {actual_row.get(field)}",
                })
    for key in sorted(set(actual) - set(expected)):
        issues.append({
            "level": "error",
            "path": str(parameter_sources_path),
            "message": f"Parameter sources CSV has unexpected row {key}",
        })


def _audit_package(package_path: Path, required_files: list[str], issues: list[dict[str, Any]]) -> None:
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            manifest = _read_archive_manifest(archive, package_path, issues)
            if manifest:
                _audit_archive_manifest_hashes(archive, manifest, issues)
    except zipfile.BadZipFile:
        issues.append({"level": "error", "path": str(package_path), "message": "Release package is not a valid zip"})
        return
    for rel_path in required_files + ["archive_manifest.json"]:
        if rel_path not in names:
            issues.append({"level": "error", "path": str(package_path), "message": f"Package missing {rel_path}"})


def _read_archive_manifest(
    archive: zipfile.ZipFile,
    package_path: Path,
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if "archive_manifest.json" not in archive.namelist():
        return None
    try:
        return json.loads(archive.read("archive_manifest.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append({
            "level": "error",
            "path": str(package_path),
            "message": f"Invalid archive_manifest.json: {exc}",
        })
        return None


def _audit_archive_manifest_hashes(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    files = manifest.get("files")
    if not isinstance(files, list):
        issues.append({"level": "error", "path": "archive_manifest.json", "message": "Manifest files must be a list"})
        return

    names = set(archive.namelist())
    manifest_paths: set[str] = set()
    for index, item in enumerate(files):
        path = item.get("path") if isinstance(item, dict) else None
        expected_hash = item.get("sha256") if isinstance(item, dict) else None
        item_path = f"archive_manifest.json:files[{index}]"
        if not path or not expected_hash:
            issues.append({"level": "error", "path": item_path, "message": "Manifest item needs path and sha256"})
            continue
        manifest_paths.add(path)
        if path not in names:
            issues.append({"level": "error", "path": item_path, "message": f"Manifest path missing from package: {path}"})
            continue
        actual_hash = hashlib.sha256(archive.read(path)).hexdigest()
        if actual_hash != expected_hash:
            issues.append({
                "level": "error",
                "path": item_path,
                "message": f"Package hash mismatch for {path}: expected {expected_hash}, got {actual_hash}",
            })

    for name in sorted(names - {"archive_manifest.json"}):
        if name not in manifest_paths:
            issues.append({
                "level": "error",
                "path": "archive_manifest.json",
                "message": f"Package file missing from manifest: {name}",
            })


def _extend_issues(target: list[dict[str, Any]], source: list[dict[str, Any]], scope: str) -> None:
    for item in source:
        copied = dict(item)
        copied["path"] = f"{scope}.{copied.get('path')}"
        target.append(copied)
