from __future__ import annotations

from wcca_cli.model_api import margin_percent, pass_fail, percent, require_requirement, value


def calculate(block: dict) -> dict:
    inputs = block.get("inputs", {})
    req = require_requirement(block)
    nominal = value(inputs, "vout_nominal")
    total_error = (
        percent(inputs, "output_accuracy")
        + percent(inputs, "load_regulation", default=0.0)
        + percent(inputs, "line_regulation", default=0.0)
    )
    worst_min = nominal * (1.0 - total_error)
    worst_max = nominal * (1.0 + total_error)
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
                "step": "total_output_error",
                "formula": "output_accuracy + load_regulation + line_regulation",
                "inputs": {"total_error_ratio": total_error},
                "result": round(total_error * 100.0, 6),
                "unit": "%",
            },
            {
                "step": "worst_min_output",
                "formula": "Vout_nominal * (1 - total_error)",
                "inputs": {"vout_nominal": nominal, "total_error_ratio": total_error},
                "result": round(worst_min, 9),
                "unit": "V",
            },
            {
                "step": "worst_max_output",
                "formula": "Vout_nominal * (1 + total_error)",
                "inputs": {"vout_nominal": nominal, "total_error_ratio": total_error},
                "result": round(worst_max, 9),
                "unit": "V",
            },
        ],
        "traceability": {"input_parameters": ["vout_nominal", "output_accuracy", "load_regulation", "line_regulation"]},
    }

