import copy
import unittest

from wcca_cli.engine import calculate_document
from wcca_cli.io import read_yaml


EXAMPLE_PATH = "wcca_models/ldo_power_rail/1.0.0/examples/basic.yaml"


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


class LdoPowerRailModelTest(unittest.TestCase):
    def test_basic_example_passes(self):
        document = _document()
        result = calculate_document(document)
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["results"][0]["summary_result"]["pass_fail"], "pass")

    def test_wide_requirement_passes(self):
        _assert_pass_fail(self, _with_requirement(_document(), 3.0, 3.6), "pass")

    def test_tight_requirement_fails(self):
        _assert_pass_fail(self, _with_requirement(_document(), 3.25, 3.35), "fail")

    def test_one_percent_accuracy_passes(self):
        _assert_pass_fail(self, _with_input_value(_document(), "output_accuracy", 1), "pass")

    def test_five_percent_accuracy_passes_sample_requirement(self):
        _assert_pass_fail(self, _with_input_value(_document(), "output_accuracy", 5), "pass")

    def test_five_volt_rail_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "vout_nominal", 5.0), 4.75, 5.25)
        _assert_pass_fail(self, document, "pass")

    def test_one_point_eight_volt_rail_passes_adjusted_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "vout_nominal", 1.8), 1.71, 1.89)
        _assert_pass_fail(self, document, "pass")

    def test_one_point_eight_volt_rail_fails_tight_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "vout_nominal", 1.8), 1.78, 1.82)
        _assert_pass_fail(self, document, "fail")

    def test_half_percent_accuracy_passes_tight_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "output_accuracy", 0.5), 3.25, 3.35)
        _assert_pass_fail(self, document, "pass")

    def test_three_percent_accuracy_passes_wider_requirement(self):
        document = _with_requirement(_with_input_value(_document(), "output_accuracy", 3), 3.2, 3.4)
        _assert_pass_fail(self, document, "pass")


if __name__ == "__main__":
    unittest.main()
