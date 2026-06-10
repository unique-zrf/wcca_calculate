from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import write_json


def run_simulation_interface(
    project_dir: str | Path,
    input_document: dict[str, Any],
    output_dir: str | Path | None = None,
    simulator: str = "not_configured",
) -> dict[str, Any]:
    root = Path(project_dir)
    target = Path(output_dir) if output_dir else root / "output" / "simulation"
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for block in input_document.get("circuit_blocks", []):
        rows.append({
            "circuit_block_id": block.get("id"),
            "circuit_block_name": block.get("name"),
            "simulator": simulator,
            "status": "skipped",
            "reason": "No external simulator command is configured.",
        })
    summary = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "skipped",
        "simulator": simulator,
        "block_count": len(rows),
        "results": rows,
        "artifacts": [
            {
                "path": str(target / "simulation_summary.csv"),
                "sha256": _file_sha256(target / "simulation_summary.csv") if (target / "simulation_summary.csv").exists() else None,
            }
        ],
    }
    _write_summary_csv(target / "simulation_summary.csv", rows)
    summary["artifacts"][0]["sha256"] = _file_sha256(target / "simulation_summary.csv")
    write_json(target / "simulation_summary.json", summary)
    return summary


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "circuit_block_id",
            "circuit_block_name",
            "simulator",
            "status",
            "reason",
        ])
        writer.writeheader()
        writer.writerows(rows)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
