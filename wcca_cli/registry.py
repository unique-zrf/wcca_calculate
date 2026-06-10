from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .io import read_yaml


ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = ROOT / "wcca_models"
REGISTRY_PATH = MODELS_ROOT / "registry.yaml"


@dataclass(frozen=True)
class ModelRef:
    model_id: str
    version: str
    path: Path
    metadata: dict[str, Any]


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry() -> dict[str, Any]:
    return read_yaml(REGISTRY_PATH)


def iter_models(status: str | None = None) -> list[ModelRef]:
    registry = load_registry()
    models: list[ModelRef] = []
    for entry in registry.get("models", []):
        model_path = ROOT / entry["path"]
        metadata = read_yaml(model_path / "model.yaml")
        if status and metadata.get("status") != status:
            continue
        models.append(ModelRef(metadata["model_id"], metadata["version"], model_path, metadata))
    return models


def get_model(model_id: str, version: str | None = None) -> ModelRef:
    matches = [m for m in iter_models() if m.model_id == model_id and (version is None or m.version == version)]
    if not matches:
        wanted = f"{model_id}:{version}" if version else model_id
        raise KeyError(f"Model not found: {wanted}")
    if version is None:
        approved = [m for m in matches if m.metadata.get("status") == "approved"]
        matches = approved or matches
        matches.sort(key=lambda m: m.version, reverse=True)
    return matches[0]


def load_implementation(model: ModelRef) -> ModuleType:
    implementation = model.path / "implementation.py"
    module_name = f"wcca_model_{model.model_id}_{model.version.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, implementation)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import model implementation: {implementation}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

