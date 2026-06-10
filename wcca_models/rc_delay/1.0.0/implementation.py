from __future__ import annotations

from wcca_cli.model_api import component_bounds, margin_percent, pass_fail, rc_delay_seconds, require_requirement, value


def calculate(block: dict) -> dict:
    inputs = block.get("inputs", {})
    req = require_requirement(block)
    r_nom, r_min, r_max = component_bounds(inputs, "r")
    c_nom, c_min, c_max = component_bounds(inputs, "c")
    v_initial_min = value(inputs, "v_initial_min")
    v_initial_max = value(inputs, "v_initial_max")
    threshold_min = value(inputs, "threshold_min")
    threshold_max = value(inputs, "threshold_max")

    nominal = rc_delay_seconds(r_nom, c_nom, (threshold_min + threshold_max) / 2.0, (v_initial_min + v_initial_max) / 2.0)
    worst_min = rc_delay_seconds(r_min, c_min, threshold_min, v_initial_max)
    worst_max = rc_delay_seconds(r_max, c_max, threshold_max, v_initial_min)
    margin_min, margin_max = margin_percent(worst_min, worst_max, req["min_value"], req["max_value"])

    return {
        "summary_result": {
            "nominal": round(nominal, 9),
            "worst_min": round(worst_min, 9),
            "worst_max": round(worst_max, 9),
            "requirement_min": req["min_value"],
            "requirement_max": req["max_value"],
            "margin_min": round(margin_min, 3),
            "margin_max": round(margin_max, 3),
            "pass_fail": pass_fail(worst_min, worst_max, req["min_value"], req["max_value"]),
        },
        "calculation_steps": [
            {
                "step": "nominal_delay",
                "formula": "-R_nominal * C_nominal * ln(1 - Vthreshold_nominal / Vinitial_nominal)",
                "inputs": {"r": r_nom, "c": c_nom},
                "result": round(nominal, 9),
                "unit": "s",
            },
            {
                "step": "worst_min_delay",
                "formula": "-R_min * C_min * ln(1 - threshold_min / v_initial_max)",
                "inputs": {"r": r_min, "c": c_min, "threshold": threshold_min, "v_initial": v_initial_max},
                "result": round(worst_min, 9),
                "unit": "s",
            },
            {
                "step": "worst_max_delay",
                "formula": "-R_max * C_max * ln(1 - threshold_max / v_initial_min)",
                "inputs": {"r": r_max, "c": c_max, "threshold": threshold_max, "v_initial": v_initial_min},
                "result": round(worst_max, 9),
                "unit": "s",
            },
        ],
        "traceability": {"input_parameters": ["r", "c", "v_initial_min", "v_initial_max", "threshold_min", "threshold_max"]},
    }

