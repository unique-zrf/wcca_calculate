from __future__ import annotations

from wcca_cli.model_api import margin_percent, pass_fail, require_requirement, resistor_bounds, value


def _threshold(vref: float, r_top: float, r_bottom: float) -> float:
    return vref * r_bottom / (r_top + r_bottom)


def calculate(block: dict) -> dict:
    inputs = block.get("inputs", {})
    req = require_requirement(block)
    vref_min = value(inputs, "vref_min")
    vref_max = value(inputs, "vref_max")
    offset = value(inputs, "input_offset", default=0.0)
    r_top_nom, r_top_min, r_top_max = resistor_bounds(inputs, "r_top")
    r_bottom_nom, r_bottom_min, r_bottom_max = resistor_bounds(inputs, "r_bottom")

    vref_nom = (vref_min + vref_max) / 2.0
    nominal = _threshold(vref_nom, r_top_nom, r_bottom_nom)
    worst_min = _threshold(vref_min, r_top_max, r_bottom_min) - abs(offset)
    worst_max = _threshold(vref_max, r_top_min, r_bottom_max) + abs(offset)
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
                "step": "nominal_threshold",
                "formula": "Vref_nominal * Rbottom_nominal / (Rtop_nominal + Rbottom_nominal)",
                "inputs": {"vref": vref_nom, "r_top": r_top_nom, "r_bottom": r_bottom_nom},
                "result": round(nominal, 9),
                "unit": "V",
            },
            {
                "step": "worst_min_threshold",
                "formula": "Vref_min * Rbottom_min / (Rtop_max + Rbottom_min) - abs(input_offset)",
                "inputs": {"vref": vref_min, "r_top": r_top_max, "r_bottom": r_bottom_min, "input_offset": offset},
                "result": round(worst_min, 9),
                "unit": "V",
            },
            {
                "step": "worst_max_threshold",
                "formula": "Vref_max * Rbottom_max / (Rtop_min + Rbottom_max) + abs(input_offset)",
                "inputs": {"vref": vref_max, "r_top": r_top_min, "r_bottom": r_bottom_max, "input_offset": offset},
                "result": round(worst_max, 9),
                "unit": "V",
            },
        ],
        "traceability": {"input_parameters": ["vref_min", "vref_max", "r_top", "r_bottom", "input_offset"]},
    }

