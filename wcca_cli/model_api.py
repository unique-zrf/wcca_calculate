from __future__ import annotations

import math
from typing import Any


class ModelInputError(ValueError):
    """Raised when a model cannot calculate from validated-looking input."""


def require_requirement(block: dict[str, Any]) -> dict[str, Any]:
    requirements = block.get("requirements") or []
    if not requirements:
        raise ModelInputError(f"{block.get('id', '<unknown>')} has no requirement")
    requirement = requirements[0]
    if "min_value" not in requirement or "max_value" not in requirement:
        raise ModelInputError(f"{block.get('id', '<unknown>')} requirement needs min_value and max_value")
    return requirement


def parameter_record(inputs: dict[str, Any], dotted_path: str) -> dict[str, Any]:
    current: Any = inputs
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ModelInputError(f"Missing parameter: {dotted_path}")
        current = current[part]
    if not isinstance(current, dict) or "value" not in current:
        raise ModelInputError(f"Parameter must be a mapping with value: {dotted_path}")
    return current


def value(inputs: dict[str, Any], dotted_path: str, default: float | None = None) -> float:
    try:
        record = parameter_record(inputs, dotted_path)
    except ModelInputError:
        if default is not None:
            return default
        raise
    try:
        return float(record["value"])
    except (TypeError, ValueError) as exc:
        raise ModelInputError(f"Parameter is not numeric: {dotted_path}") from exc


def percent(inputs: dict[str, Any], dotted_path: str, default: float = 0.0) -> float:
    return value(inputs, dotted_path, default=default) / 100.0


def resistor_bounds(inputs: dict[str, Any], prefix: str) -> tuple[float, float, float]:
    nominal = value(inputs, f"{prefix}.nominal")
    tolerance = percent(inputs, f"{prefix}.tolerance", default=0.0)
    aging = percent(inputs, f"{prefix}.aging", default=0.0)
    tempco_ppm = value(inputs, f"{prefix}.tempco", default=0.0)
    temp_min = value(inputs, "temperature_min", default=25.0)
    temp_max = value(inputs, "temperature_max", default=25.0)
    temp_delta = max(abs(temp_min - 25.0), abs(temp_max - 25.0))
    temp_ratio = tempco_ppm * temp_delta / 1_000_000.0
    total = tolerance + aging + temp_ratio
    return nominal, nominal * (1.0 - total), nominal * (1.0 + total)


def component_bounds(inputs: dict[str, Any], prefix: str) -> tuple[float, float, float]:
    nominal = value(inputs, f"{prefix}.nominal")
    tolerance = percent(inputs, f"{prefix}.tolerance", default=0.0)
    aging = percent(inputs, f"{prefix}.aging", default=0.0)
    total = tolerance + aging
    return nominal, nominal * (1.0 - total), nominal * (1.0 + total)


def margin_percent(worst_min: float, worst_max: float, req_min: float, req_max: float) -> tuple[float, float]:
    span = req_max - req_min
    if span <= 0:
        raise ModelInputError("Requirement max must be greater than min")
    margin_min = (worst_min - req_min) / span * 100.0
    margin_max = (req_max - worst_max) / span * 100.0
    return margin_min, margin_max


def pass_fail(worst_min: float, worst_max: float, req_min: float, req_max: float) -> str:
    return "pass" if worst_min >= req_min and worst_max <= req_max else "fail"


def rc_delay_seconds(r_ohm: float, c_farad: float, threshold_v: float, initial_v: float) -> float:
    if initial_v <= 0:
        raise ModelInputError("initial voltage must be positive")
    ratio = threshold_v / initial_v
    if ratio <= 0 or ratio >= 1:
        raise ModelInputError("threshold / initial voltage must be between 0 and 1")
    return -r_ohm * c_farad * math.log(1.0 - ratio)

