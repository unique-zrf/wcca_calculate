import copy
import unittest

from wcca_cli.engine import calculate_document
from wcca_cli.io import read_yaml


EXAMPLE_PATH = "wcca_models/resistor_divider/1.0.0/examples/basic.yaml"


def _document() -> dict:
    return read_yaml(EXAMPLE_PATH)


def _with_requirement(document: dict, min_value: float, max_value: float) -> dict:
    clone = copy.deepcopy(document)
    requirement = clone["circuit_blocks"][0]["requirements"][0]
    requirement["min_value"] = min_value
    requirement["max_value"] = max_value
    return clone


def _with_input_value(document: dict, dotted_path: str, value: float) -> dict:
    clone = copy.deepcopy(document)
    node = clone["circuit_blocks"][0]["inputs"]
    for part in dotted_path.split(".")[:-1]:
        node = node[part]
    node[dotted_path.split(".")[-1]]["value"] = value
    return clone


def _assert_pass_fail(test_case: unittest.TestCase, document: dict, expected: str) -> None:
    result = calculate_document(document)
    test_case.assertEqual(result["status"], "calculated")
    test_case.assertEqual(result["results"][0]["summary_result"]["pass_fail"], expected)


class ResistorDividerModelTest(unittest.TestCase):
    def test_basic_example_passes(self):
        document = _document()
        result = calculate_document(document)
        self.assertEqual(result["status"], "calculated")
        summary = result["results"][0]["summary_result"]
        self.assertEqual(summary["pass_fail"], "pass")
        self.assertLess(summary["worst_min"], summary["worst_max"])

    def test_wide_requirement_passes(self):
        _assert_pass_fail(self, _with_requirement(_document(), 0.30, 0.70), "pass")

    def test_tight_requirement_fails(self):
        _assert_pass_fail(self, _with_requirement(_document(), 0.45, 0.48), "fail")

    def test_low_input_voltage_can_fail_requirement(self):
        _assert_pass_fail(self, _with_input_value(_document(), "vin_min", 4.5), "fail")

    def test_high_input_voltage_keeps_requirement(self):
        _assert_pass_fail(self, _with_input_value(_document(), "vin_max", 5.5), "pass")

    def test_small_top_resistor_tolerance_passes(self):
        _assert_pass_fail(self, _with_input_value(_document(), "r_top.tolerance", 0.1), "pass")

    def test_large_bottom_resistor_tolerance_fails(self):
        _assert_pass_fail(self, _with_input_value(_document(), "r_bottom.tolerance", 5), "fail")

    def test_changed_top_resistor_value_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_top.nominal", 110000), 0.35, 0.55)
        _assert_pass_fail(self, document, "pass")

    def test_changed_bottom_resistor_value_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_bottom.nominal", 12000), 0.45, 0.70)
        _assert_pass_fail(self, document, "pass")

    def test_low_bottom_resistor_value_fails_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_bottom.nominal", 5000), 0.40, 0.55)
        _assert_pass_fail(self, document, "fail")


if __name__ == "__main__":
    unittest.main()
