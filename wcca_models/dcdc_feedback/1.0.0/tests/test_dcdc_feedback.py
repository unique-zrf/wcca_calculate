import copy
import unittest

from wcca_cli.engine import calculate_document
from wcca_cli.io import read_yaml


EXAMPLE_PATH = "wcca_models/dcdc_feedback/1.0.0/examples/basic.yaml"


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
    test_case.assertEqual(result["status"], "calculated", result)
    test_case.assertEqual(result["results"][0]["summary_result"]["pass_fail"], expected)


class DcdcFeedbackModelTest(unittest.TestCase):
    def test_basic_example_passes(self):
        document = _document()
        result = calculate_document(document)
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["results"][0]["summary_result"]["pass_fail"], "pass")

    def test_wide_requirement_passes(self):
        _assert_pass_fail(self, _with_requirement(_document(), 4.5, 5.5), "pass")

    def test_tight_requirement_fails(self):
        _assert_pass_fail(self, _with_requirement(_document(), 4.95, 5.05), "fail")

    def test_lower_reference_fails_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "vref_min", 0.780), 4.75, 5.25)
        _assert_pass_fail(self, document, "fail")

    def test_higher_reference_fails_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "vref_max", 0.830), 4.75, 5.25)
        _assert_pass_fail(self, document, "fail")

    def test_small_resistor_tolerance_passes_tighter_requirement(self):
        document = _with_input_value(_with_input_value(_document(), "r_top.tolerance", 0.1), "r_bottom.tolerance", 0.1)
        _assert_pass_fail(self, _with_requirement(document, 4.8, 5.2), "pass")

    def test_large_top_tolerance_fails_tight_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_top.tolerance", 5), 4.75, 5.25)
        _assert_pass_fail(self, document, "fail")

    def test_large_bottom_tolerance_fails_tight_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_bottom.tolerance", 5), 4.75, 5.25)
        _assert_pass_fail(self, document, "fail")

    def test_lower_output_setpoint_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "r_top.nominal", 100000), 4.55, 5.1)
        _assert_pass_fail(self, document, "pass")

    def test_higher_output_setpoint_fails_sample_requirement(self):
        document = _with_input_value(_document(), "r_top.nominal", 120000)
        _assert_pass_fail(self, document, "fail")


if __name__ == "__main__":
    unittest.main()
