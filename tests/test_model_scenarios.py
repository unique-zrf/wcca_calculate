import copy
import unittest
from pathlib import Path

from wcca_cli.engine import calculate_document
from wcca_cli.io import read_yaml


def single_block_document(example_path: str) -> dict:
    return read_yaml(example_path)


def set_requirement(document: dict, min_value: float, max_value: float) -> dict:
    clone = copy.deepcopy(document)
    requirement = clone["circuit_blocks"][0]["requirements"][0]
    requirement["min_value"] = min_value
    requirement["max_value"] = max_value
    return clone


def set_input_value(document: dict, dotted_path: str, value: float) -> dict:
    clone = copy.deepcopy(document)
    node = clone["circuit_blocks"][0]["inputs"]
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]]["value"] = value
    return clone


def calculate_pass_fail(document: dict) -> str:
    result = calculate_document(document)
    if result["status"] != "calculated":
        raise AssertionError(result)
    return result["results"][0]["summary_result"]["pass_fail"]


class ModelScenarioCoverageTest(unittest.TestCase):
    def test_each_model_has_at_least_three_example_files(self):
        for examples_dir in Path("wcca_models").glob("*/1.0.0/examples"):
            with self.subTest(examples_dir=examples_dir):
                examples = list(examples_dir.glob("*.yaml"))
                self.assertGreaterEqual(len(examples), 3)

    def test_resistor_divider_has_ten_scenarios(self):
        base = single_block_document("wcca_models/resistor_divider/1.0.0/examples/basic.yaml")
        cases = [
            (base, "pass"),
            (set_requirement(base, 0.30, 0.70), "pass"),
            (set_requirement(base, 0.45, 0.48), "fail"),
            (set_input_value(base, "vin_min", 4.5), "fail"),
            (set_input_value(base, "vin_max", 5.5), "pass"),
            (set_input_value(base, "r_top.tolerance", 0.1), "pass"),
            (set_input_value(base, "r_bottom.tolerance", 5), "fail"),
            (set_requirement(set_input_value(base, "r_top.nominal", 110000), 0.35, 0.55), "pass"),
            (set_requirement(set_input_value(base, "r_bottom.nominal", 12000), 0.45, 0.70), "pass"),
            (set_requirement(set_input_value(base, "r_bottom.nominal", 5000), 0.40, 0.55), "fail"),
        ]
        self.assertGreaterEqual(len(cases), 10)
        for index, (document, expected) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(calculate_pass_fail(document), expected)

    def test_ldo_power_rail_has_ten_scenarios(self):
        base = single_block_document("wcca_models/ldo_power_rail/1.0.0/examples/basic.yaml")
        cases = [
            (base, "pass"),
            (set_requirement(base, 3.0, 3.6), "pass"),
            (set_requirement(base, 3.25, 3.35), "fail"),
            (set_input_value(base, "output_accuracy", 1), "pass"),
            (set_input_value(base, "output_accuracy", 5), "pass"),
            (set_requirement(set_input_value(base, "vout_nominal", 5.0), 4.75, 5.25), "pass"),
            (set_requirement(set_input_value(base, "vout_nominal", 1.8), 1.71, 1.89), "pass"),
            (set_requirement(set_input_value(base, "vout_nominal", 1.8), 1.78, 1.82), "fail"),
            (set_requirement(set_input_value(base, "output_accuracy", 0.5), 3.25, 3.35), "pass"),
            (set_requirement(set_input_value(base, "output_accuracy", 3), 3.2, 3.4), "pass"),
        ]
        self.assertGreaterEqual(len(cases), 10)
        for index, (document, expected) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(calculate_pass_fail(document), expected)

    def test_comparator_threshold_has_ten_scenarios(self):
        base = single_block_document("wcca_models/comparator_threshold/1.0.0/examples/basic.yaml")
        cases = [
            (base, "pass"),
            (set_requirement(base, 1.0, 1.5), "pass"),
            (set_requirement(base, 1.24, 1.26), "fail"),
            (set_input_value(base, "input_offset", 0.001), "pass"),
            (set_requirement(set_input_value(base, "input_offset", 0.1), 1.1, 1.4), "pass"),
            (set_requirement(set_input_value(base, "input_offset", 0.2), 1.1, 1.4), "fail"),
            (set_requirement(set_input_value(base, "vref_min", 2.3), 1.0, 1.4), "pass"),
            (set_requirement(set_input_value(base, "vref_max", 2.7), 1.1, 1.5), "pass"),
            (set_requirement(set_input_value(base, "r_top.tolerance", 5), 1.0, 1.5), "pass"),
            (set_requirement(set_input_value(base, "r_bottom.nominal", 50000), 1.1, 1.4), "fail"),
        ]
        self.assertGreaterEqual(len(cases), 10)
        for index, (document, expected) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(calculate_pass_fail(document), expected)

    def test_rc_delay_has_ten_scenarios(self):
        base = single_block_document("wcca_models/rc_delay/1.0.0/examples/basic.yaml")
        cases = [
            (base, "pass"),
            (set_requirement(base, 0.004, 0.02), "pass"),
            (set_requirement(base, 0.008, 0.010), "fail"),
            (set_input_value(base, "r.tolerance", 0.1), "pass"),
            (set_input_value(base, "c.tolerance", 1), "pass"),
            (set_requirement(set_input_value(base, "c.nominal", 0.0000001), 0.006, 0.014), "fail"),
            (set_requirement(set_input_value(base, "c.nominal", 0.00000033), 0.006, 0.02), "pass"),
            (set_requirement(set_input_value(base, "threshold_max", 1.4), 0.006, 0.02), "pass"),
            (set_requirement(set_input_value(base, "threshold_min", 0.8), 0.004, 0.014), "pass"),
            (set_requirement(set_input_value(base, "v_initial_min", 2.8), 0.006, 0.014), "pass"),
        ]
        self.assertGreaterEqual(len(cases), 10)
        for index, (document, expected) in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(calculate_pass_fail(document), expected)


if __name__ == "__main__":
    unittest.main()
