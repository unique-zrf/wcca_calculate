from __future__ import annotations

import copy
from typing import Any


UNIT_ALIASES = {
    "v": "V",
    "volt": "V",
    "volts": "V",
    "mv": "mV",
    "uv": "uV",
    "ohm": "ohm",
    "ohms": "ohm",
    "Ω": "ohm",
    "kohm": "kohm",
    "kΩ": "kohm",
    "mohm": "Mohm",
    "mΩ": "Mohm",
    "f": "F",
    "farad": "F",
    "farads": "F",
    "uf": "uF",
    "µf": "uF",
    "nf": "nF",
    "pf": "pF",
    "s": "s",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "ms": "ms",
    "us": "us",
    "µs": "us",
    "ns": "ns",
    "%": "%",
    "percent": "%",
    "ppm/c": "ppm/C",
    "ppm/°c": "ppm/C",
    "ppmc": "ppm/C",
    "degc": "degC",
    "°c": "degC",
}

CONVERSIONS = {
    ("V", "V"): 1.0,
    ("mV", "V"): 1e-3,
    ("uV", "V"): 1e-6,
    ("ohm", "ohm"): 1.0,
    ("kohm", "ohm"): 1e3,
    ("Mohm", "ohm"): 1e6,
    ("F", "F"): 1.0,
    ("uF", "F"): 1e-6,
    ("nF", "F"): 1e-9,
    ("pF", "F"): 1e-12,
    ("s", "s"): 1.0,
    ("ms", "s"): 1e-3,
    ("us", "s"): 1e-6,
    ("ns", "s"): 1e-9,
    ("%", "%"): 1.0,
    ("ppm/C", "ppm/C"): 1.0,
    ("degC", "degC"): 1.0,
}

BASE_UNITS = {
    "V": "V",
    "mV": "V",
    "uV": "V",
    "ohm": "ohm",
    "kohm": "ohm",
    "Mohm": "ohm",
    "F": "F",
    "uF": "F",
    "nF": "F",
    "pF": "F",
    "s": "s",
    "ms": "s",
    "us": "s",
    "ns": "s",
    "%": "%",
    "ppm/C": "ppm/C",
    "degC": "degC",
}


def canonical_unit(unit: Any) -> str:
    text = str(unit or "").strip()
    if not text:
        return ""
    return UNIT_ALIASES.get(text.lower(), text)


def can_convert_unit(actual_unit: Any, expected_unit: Any) -> bool:
    return (canonical_unit(actual_unit), canonical_unit(expected_unit)) in CONVERSIONS


def convert_value(value: Any, actual_unit: Any, expected_unit: Any) -> float:
    actual = canonical_unit(actual_unit)
    expected = canonical_unit(expected_unit)
    key = (actual, expected)
    if key not in CONVERSIONS:
        raise ValueError(f"Cannot convert unit {actual_unit} to {expected_unit}")
    return float(value) * CONVERSIONS[key]


def base_unit(unit: Any) -> str:
    canonical = canonical_unit(unit)
    return BASE_UNITS.get(canonical, canonical)


def normalize_document_units(
    document: dict[str, Any],
    expected_units_by_block: dict[str | None, dict[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = copy.deepcopy(document)
    conversions: list[dict[str, Any]] = []
    for block in normalized.get("circuit_blocks", []):
        block_expected_units = (expected_units_by_block or {}).get(block.get("id"), {})
        for requirement in block.get("requirements", []):
            _normalize_requirement(requirement, block.get("id"), conversions)
        _normalize_input_node(block.get("inputs", {}), block.get("id"), "", conversions, block_expected_units)
    return normalized, conversions


def _normalize_requirement(
    requirement: dict[str, Any],
    block_id: str | None,
    conversions: list[dict[str, Any]],
) -> None:
    unit = requirement.get("unit")
    if not unit:
        return
    target_unit = base_unit(unit)
    if not can_convert_unit(unit, target_unit):
        return
    if canonical_unit(unit) == target_unit:
        requirement["unit"] = target_unit
        return
    for key in ("min_value", "max_value"):
        if key in requirement and requirement[key] is not None:
            requirement[key] = convert_value(requirement[key], unit, target_unit)
    requirement["unit"] = target_unit
    conversions.append({
        "circuit_block_id": block_id,
        "parameter": f"requirements.{requirement.get('id')}",
        "from_unit": unit,
        "to_unit": target_unit,
    })


def _normalize_input_node(
    node: Any,
    block_id: str | None,
    path: str,
    conversions: list[dict[str, Any]],
    expected_units: dict[str, str],
) -> None:
    if isinstance(node, dict) and "value" in node and "unit" in node:
        original_unit = node.get("unit")
        target_unit = expected_units.get(path, base_unit(original_unit))
        if canonical_unit(original_unit) != target_unit and can_convert_unit(original_unit, target_unit):
            node["value"] = convert_value(node["value"], original_unit, target_unit)
            node["unit"] = target_unit
            conversions.append({
                "circuit_block_id": block_id,
                "parameter": path,
                "from_unit": original_unit,
                "to_unit": target_unit,
            })
        else:
            node["unit"] = target_unit
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            _normalize_input_node(value, block_id, child_path, conversions, expected_units)
