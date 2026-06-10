from __future__ import annotations

from wcca_cli.model_api import margin_percent, pass_fail, require_requirement, resistor_bounds, value


def _feedback_output(vref: float, r_top: float, r_bottom: float) -> float:
    return vref * (1.0 + r_top / r_bottom)


def calculate(block: dict) -> dict:
    inputs = block.get("inputs", {})
    req = require_requirement(block)
    vref_min = value(inputs, "vref_min")
    vref_max = value(inputs, "vref_max")
    r_top_nom, r_top_min, r_top_max = resistor_bounds(inputs, "r_top")
    r_bottom_nom, r_bottom_min, r_bottom_max = resistor_bounds(inputs, "r_bottom")

    vref_nominal = (vref_min + vref_max) / 2.0
    nominal = _feedback_output(vref_nominal, r_top_nom, r_bottom_nom)
    worst_min = _feedback_output(vref_min, r_top_min, r_bottom_max)
    worst_max = _feedback_output(vref_max, r_top_max, r_bottom_min)
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
                "step": "nominal_output",
                "formula": "Vref_nominal * (1 + Rtop_nominal / Rbottom_nominal)",
                "inputs": {"vref": vref_nominal, "r_top": r_top_nom, "r_bottom": r_bottom_nom},
                "result": round(nominal, 9),
                "unit": "V",
            },
            {
                "step": "worst_min_output",
                "formula": "Vref_min * (1 + Rtop_min / Rbottom_max)",
                "inputs": {"vref": vref_min, "r_top": r_top_min, "r_bottom": r_bottom_max},
                "result": round(worst_min, 9),
                "unit": "V",
            },
            {
                "step": "worst_max_output",
                "formula": "Vref_max * (1 + Rtop_max / Rbottom_min)",
                "inputs": {"vref": vref_max, "r_top": r_top_max, "r_bottom": r_bottom_min},
                "result": round(worst_max, 9),
                "unit": "V",
            },
        ],
        "traceability": {"input_parameters": ["vref_min", "vref_max", "r_top", "r_bottom"]},
    }
