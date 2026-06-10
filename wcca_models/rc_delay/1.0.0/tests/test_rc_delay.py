import copy
import unittest

from wcca_cli.engine import calculate_document
from wcca_cli.io import read_yaml


EXAMPLE_PATH = "wcca_models/rc_delay/1.0.0/examples/basic.yaml"


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


class RcDelayModelTest(unittest.TestCase):
    def test_basic_example_passes(self):
        document = _document()
        result = calculate_document(document)
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["results"][0]["summary_result"]["pass_fail"], "pass")

    def test_wide_requirement_passes(self):
        _assert_pass_fail(self, _with_requirement(_document(), 0.004, 0.02), "pass")

    def test_tight_requirement_fails(self):
        _assert_pass_fail(self, _with_requirement(_document(), 0.008, 0.010), "fail")

    def test_small_resistor_tolerance_passes(self):
        _assert_pass_fail(self, _with_input_value(_document(), "r.tolerance", 0.1), "pass")

    def test_large_capacitor_tolerance_passes_sample_requirement(self):
        _assert_pass_fail(self, _with_input_value(_document(), "c.tolerance", 1), "pass")

    def test_small_capacitor_fails_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "c.nominal", 0.0000001), 0.006, 0.014)
        _assert_pass_fail(self, document, "fail")

    def test_larger_capacitor_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "c.nominal", 0.00000033), 0.006, 0.02)
        _assert_pass_fail(self, document, "pass")

    def test_higher_threshold_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "threshold_max", 1.4), 0.006, 0.02)
        _assert_pass_fail(self, document, "pass")

    def test_lower_threshold_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "threshold_min", 0.8), 0.004, 0.014)
        _assert_pass_fail(self, document, "pass")

    def test_lower_initial_voltage_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "v_initial_min", 2.8), 0.006, 0.014)
        _assert_pass_fail(self, document, "pass")


if __name__ == "__main__":
    unittest.main()
