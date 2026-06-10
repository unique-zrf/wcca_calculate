from __future__ import annotations

import csv
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_yaml, write_json
from .workflow import load_review_workflow


def build_enterprise_payload(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    input_document = _load_yaml(root / "work" / "wcca_input.yaml")
    results_document = _load_json(root / "output" / "calculation" / "results.json")
    approval_document = _load_json(root / "review" / "approvals" / "approval_record.json")
    workflow_document = _load_json(root / "review" / "workflow.json") or load_review_workflow(root)
    report_document = _load_text(root / "output" / "report" / "wcca_report.md")
    return {
        "generated_at": _now(),
        "project_dir": str(root),
        "project_name": input_document.get("project", {}).get("name") if input_document else root.name,
        "block_count": len(input_document.get("circuit_blocks", [])) if input_document else 0,
        "result_count": len(results_document.get("results", [])) if results_document else 0,
        "release_status": results_document.get("release_status") if results_document else None,
        "approval": {
            "decision": approval_document.get("decision") if approval_document else None,
            "reviewer": approval_document.get("reviewer") if approval_document else None,
            "validation_status": approval_document.get("validation_status") if approval_document else None,
        },
        "workflow": {
            "state": workflow_document.get("state", "draft"),
            "history_count": len(workflow_document.get("history", [])),
            "release_ready": workflow_document.get("readiness", {}).get("release_ready", False),
        },
        "report_available": bool(report_document),
        "blocks": _block_summaries(input_document or {}, results_document or {}),
        "risk_items": (results_document or {}).get("risk_items", []),
        "requirements_coverage": (results_document or {}).get("requirements_coverage", []),
        "parameter_sources": (results_document or {}).get("parameter_sources", []),
    }


def dispatch_enterprise_integration(
    project_dir: str | Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_dir)
    payload = build_enterprise_payload(root)
    provider_config = _normalize_config(config)
    manifest = {
        "generated_at": _now(),
        "project_dir": str(root),
        "provider": provider_config.get("provider", "filesystem"),
        "targets": [],
        "payload_sha256": _sha256_json(payload),
    }

    targets = _expand_targets(provider_config)
    for index, target in enumerate(targets):
        result = _dispatch_target(root, payload, target, index)
        manifest["targets"].append(result)

    output_dir = root / "output" / "integration"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "integration_manifest.json", manifest)
    _write_payload_snapshot(output_dir / "integration_payload.json", payload)
    _write_summary_csv(output_dir / "integration_summary.csv", payload)
    return manifest


def _dispatch_target(root: Path, payload: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, Any]:
    provider = str(config.get("provider", "filesystem")).lower()
    if provider in {"filesystem", "file", "local"}:
        return _dispatch_filesystem(root, payload, config, index)
    if provider in {"webhook", "http"}:
        return _dispatch_webhook(payload, config, index)
    raise ValueError(f"Unsupported enterprise integration provider: {provider}")


def _dispatch_filesystem(root: Path, payload: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, Any]:
    output_dir = Path(config.get("output_dir") or root / "output" / "integration" / f"filesystem_{index}")
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / str(config.get("payload_filename", "payload.json"))
    write_json(payload_path, payload)
    summary_path = output_dir / str(config.get("summary_filename", "summary.csv"))
    _write_summary_csv(summary_path, payload)
    return {
        "provider": "filesystem",
        "status": "completed",
        "output_dir": str(output_dir),
        "payload_path": str(payload_path),
        "summary_path": str(summary_path),
        "sha256": _sha256_path(payload_path),
    }


def _dispatch_webhook(payload: dict[str, Any], config: dict[str, Any], index: int) -> dict[str, Any]:
    base_url = str(config.get("base_url", "")).rstrip("/")
    endpoint = str(config.get("endpoint", "/api/integration")).lstrip("/")
    if not base_url:
        raise ValueError("Webhook integration requires base_url")
    request = urllib.request.Request(
        f"{base_url}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(config),
        method=str(config.get("method", "POST")).upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout_seconds", 30))) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "provider": "webhook",
                "status": "completed",
                "http_status": getattr(response, "status", 200),
                "response_preview": body[:500],
                "target_index": index,
            }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "provider": "webhook",
            "status": "failed",
            "error": str(exc),
            "target_index": index,
        }


def _block_summaries(input_document: dict[str, Any], results_document: dict[str, Any]) -> list[dict[str, Any]]:
    result_by_block = {
        item.get("circuit_block_id"): item
        for item in results_document.get("results", [])
    }
    summaries: list[dict[str, Any]] = []
    for block in input_document.get("circuit_blocks", []):
        result = result_by_block.get(block.get("id"), {})
        summary = result.get("summary_result", {})
        summaries.append({
            "circuit_block_id": block.get("id"),
            "model_id": block.get("selected_model", {}).get("model_id"),
            "model_version": block.get("selected_model", {}).get("model_version"),
            "pass_fail": summary.get("pass_fail"),
            "worst_min": summary.get("worst_min"),
            "worst_max": summary.get("worst_max"),
        })
    return summaries


def _write_summary_csv(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["circuit_block_id", "model_id", "model_version", "pass_fail", "worst_min", "worst_max"])
        writer.writeheader()
        for row in payload.get("blocks", []):
            writer.writerow(row)


def _write_payload_snapshot(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {"provider": "filesystem"}
    normalized = dict(config)
    normalized.setdefault("provider", "filesystem")
    return normalized


def _expand_targets(config: dict[str, Any]) -> list[dict[str, Any]]:
    provider = str(config.get("provider", "filesystem")).lower()
    if provider == "combined":
        targets = config.get("targets")
        if isinstance(targets, list) and targets:
            return [item if isinstance(item, dict) else {"provider": "filesystem"} for item in targets]
        return [{"provider": "filesystem"}]
    return [config]


def _load_yaml(path: Path) -> dict[str, Any]:
    return read_yaml(path) if path.exists() else {}


def _load_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(config.get("headers", {}))
    return headers


def _sha256_json(payload: dict[str, Any]) -> str:
    import hashlib

    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
