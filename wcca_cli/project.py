from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import write_yaml


INPUT_DIRS = [
    "input/schematic",
    "input/netlist",
    "input/bom",
    "input/datasheets",
    "input/requirements",
    "input/standards",
    "input/simulation",
]

WORK_DIRS = ["work/extracted", "work/normalized"]
OUTPUT_DIRS = ["output/calculation", "output/report", "output/traceability", "output/risk"]
REVIEW_DIRS = ["review/comments", "review/approvals"]


def init_project(project_dir: str | Path, project_name: str | None = None) -> Path:
    root = Path(project_dir)
    for rel_dir in INPUT_DIRS + WORK_DIRS + OUTPUT_DIRS + REVIEW_DIRS + ["release"]:
        (root / rel_dir).mkdir(parents=True, exist_ok=True)
    sample_input = root / "work" / "wcca_input.yaml"
    if not sample_input.exists():
        write_yaml(sample_input, _empty_input(project_name or root.name))
    return root


def ingest_project(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    input_root = root / "input"
    documents = []
    if input_root.exists():
        for path in sorted(input_root.rglob("*")):
            if path.is_file():
                documents.append({
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "size_bytes": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
                    "category": _category(path, input_root),
                })
    index = {
        "project_dir": str(root),
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "documents": documents,
        "missing_input_categories": _missing_categories(input_root),
    }
    write_yaml(root / "work" / "input_index.yaml", index)
    return index


def _empty_input(project_name: str) -> dict[str, Any]:
    return {
        "project": {
            "name": project_name,
            "document_type": "WCCA",
        },
        "circuit_blocks": [],
    }


def _category(path: Path, input_root: Path) -> str:
    try:
        rel = path.relative_to(input_root)
    except ValueError:
        return "unknown"
    return rel.parts[0] if rel.parts else "unknown"


def _missing_categories(input_root: Path) -> list[str]:
    missing = []
    for rel_dir in INPUT_DIRS:
        category = rel_dir.split("/", 1)[1]
        category_dir = input_root / category
        has_file = category_dir.exists() and any(path.is_file() for path in category_dir.rglob("*"))
        if not has_file:
            missing.append(category)
    return missing

