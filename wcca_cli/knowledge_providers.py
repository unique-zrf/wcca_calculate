from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import read_yaml
from .knowledge import search_knowledge


@dataclass(frozen=True)
class KnowledgeHit:
    provider: str
    title: str
    content: str
    source: str
    score: float | None = None
    metadata: dict[str, Any] | None = None


def load_knowledge_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"provider": "local"}
    config = read_yaml(path)
    if "provider" not in config:
        config["provider"] = "local"
    return config


def query_knowledge(query: str, config: dict[str, Any] | None = None, limit: int = 5) -> list[KnowledgeHit]:
    provider_config = config or {"provider": "local"}
    provider = str(provider_config.get("provider", "local")).lower()
    if provider == "local":
        return _query_local(query, limit)
    if provider == "ragflow":
        return _query_ragflow(query, provider_config, limit)
    if provider in {"hardware", "hardware_database", "hardware-rag"}:
        return _query_hardware_database(query, provider_config, limit)
    raise ValueError(f"Unsupported knowledge provider: {provider}")


def _query_local(query: str, limit: int) -> list[KnowledgeHit]:
    hits = []
    for item in search_knowledge(query, limit=limit):
        hits.append(KnowledgeHit(
            provider="local",
            title=item.get("title", ""),
            content=item.get("summary", ""),
            source=item.get("path", item.get("id", "")),
            score=float(item.get("score", 0)),
            metadata={"id": item.get("id"), "doc_type": item.get("doc_type")},
        ))
    return hits


def _query_ragflow(query: str, config: dict[str, Any], limit: int) -> list[KnowledgeHit]:
    base_url = str(config.get("base_url", "")).rstrip("/")
    endpoint = str(config.get("endpoint", "/api/v1/retrieval")).lstrip("/")
    if not base_url:
        raise ValueError("RAGFlow provider requires base_url")
    payload = dict(config.get("payload", {}))
    payload.setdefault("question", query)
    payload.setdefault("query", query)
    payload.setdefault("top_k", limit)
    if config.get("dataset_id"):
        payload.setdefault("dataset_id", config["dataset_id"])
    request = urllib.request.Request(
        f"{base_url}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_ragflow_headers(config),
        method=str(config.get("method", "POST")).upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout_seconds", 30))) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"RAGFlow query failed: {exc}") from exc
    return _hits_from_ragflow_response(data, limit)


def _ragflow_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(config.get("headers", {}))
    return headers


def _hits_from_ragflow_response(data: Any, limit: int) -> list[KnowledgeHit]:
    candidates = []
    if isinstance(data, dict):
        for key in ("chunks", "documents", "data", "result", "records"):
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and isinstance(data.get("answer"), str):
            candidates = [data]
    elif isinstance(data, list):
        candidates = data

    hits = []
    for item in candidates[:limit]:
        if isinstance(item, str):
            hits.append(KnowledgeHit(provider="ragflow", title="RAGFlow result", content=item, source="ragflow"))
            continue
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or item.get("answer") or item.get("chunk") or "")
        title = str(item.get("title") or item.get("document_name") or item.get("name") or "RAGFlow result")
        source = str(item.get("source") or item.get("document_id") or item.get("id") or "ragflow")
        score = item.get("score") or item.get("similarity")
        hits.append(KnowledgeHit(
            provider="ragflow",
            title=title,
            content=content,
            source=source,
            score=float(score) if isinstance(score, (int, float)) else None,
            metadata=item,
        ))
    return hits


def _query_hardware_database(query: str, config: dict[str, Any], limit: int) -> list[KnowledgeHit]:
    root = Path(config.get("path", r"D:\workspace\git_workspace\Hardware-DataBase"))
    kb_name = str(config.get("kb_name", config.get("knowledge_base", "default")))
    if not root.exists():
        raise ValueError(f"Hardware-DataBase path does not exist: {root}")
    sys.path.insert(0, str(root))
    try:
        from src.core.rag_pipeline import RAGPipeline  # type: ignore

        pipeline = RAGPipeline()
        answer = "".join(pipeline.query(query, kb_name, []))
    except Exception as exc:
        if config.get("fallback_to_files", True):
            return _query_hardware_files(root, query, limit, str(exc))
        raise RuntimeError(f"Hardware-DataBase query failed: {exc}") from exc
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass
    return [KnowledgeHit(
        provider="hardware",
        title=f"Hardware-DataBase:{kb_name}",
        content=answer,
        source=str(root),
        metadata={"kb_name": kb_name, "limit": limit},
    )]


def _query_hardware_files(root: Path, query: str, limit: int, provider_error: str) -> list[KnowledgeHit]:
    terms = [term.lower() for term in query.split() if term.strip()]
    searchable_roots = [root / "data", root / "docs"]
    candidates: list[KnowledgeHit] = []
    for base in searchable_roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".csv", ".yaml", ".yml", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="ignore")
            lowered = text.lower()
            score = sum(lowered.count(term) for term in terms) if terms else 1
            if score <= 0:
                continue
            candidates.append(KnowledgeHit(
                provider="hardware-files",
                title=path.name,
                content=_excerpt(text, terms),
                source=str(path),
                score=float(score),
                metadata={"fallback_reason": provider_error},
            ))
    candidates.sort(key=lambda item: (-(item.score or 0), item.source))
    return candidates[:limit]


def _excerpt(text: str, terms: list[str], size: int = 800) -> str:
    if not text:
        return ""
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(min(positions) - size // 4, 0) if positions else 0
    return text[start:start + size]
