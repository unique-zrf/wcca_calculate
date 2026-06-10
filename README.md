# WCCA Automation Toolkit

This repository implements the first executable slice of `WCCA计算模型库与知识库接入规划方案.md`.

Phase 1 scope:

- WCCA Core CLI
- Four approved calculation models
- Local file knowledge cards
- Example `wcca_input.yaml`
- Unit/regression tests

Run the sample:

```bash
python -m wcca_cli init --project examples/new_project --name NewProject
python -m wcca_cli ingest --project examples/new_project
python -m wcca_cli extract --project examples/new_project
python -m wcca_cli normalize --project examples/new_project
python -m wcca_cli input-build --project examples/new_project
python -m wcca_cli model list --status approved
python -m wcca_cli model diff resistor_divider --from-version 1.0.0 --to-version 1.0.0
python -m wcca_cli validate-kb
python -m wcca_cli kb search "RC0402FR-07100KL"
python -m wcca_cli kb show DS-LDO
python -m wcca_cli kb search "typical worst case"
python -m wcca_cli kb show KB-MODEL-resistor_divider-1.0.0
python -m wcca_cli validate-input --input examples/project_sample/work/wcca_input.yaml
python -m wcca_cli calculate --input examples/project_sample/work/wcca_input.yaml --output examples/project_sample/output/calculation
python -m wcca_cli validate --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json
python -m wcca_cli report --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/output/report
python -m wcca_cli review-checklist --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/review/comments
python -m wcca_cli approve --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/review/approvals --reviewer sample_engineer --decision approved
python -m wcca_cli package --project examples/project_sample --output examples/project_sample/release/wcca_package.zip
python -m wcca_cli audit --project examples/project_sample
```

For the included sample project, `extract` reads `examples/project_sample/input/bom/sample_bom.csv`, `examples/project_sample/input/netlist/sample_netlist.csv`, and `examples/project_sample/input/requirements/requirements.csv`, then writes:

- `examples/project_sample/work/extracted/components.yaml`
- `examples/project_sample/work/extracted/parameter_draft.yaml`
- `examples/project_sample/work/extracted/netlist.yaml`
- `examples/project_sample/work/extracted/requirements.yaml`

`normalize` then writes:

- `examples/project_sample/work/normalized/parameters.yaml`
- `examples/project_sample/work/normalized/model_candidates.yaml`

When netlist files are present, model candidates include topology evidence such as shared signal nets for resistor dividers and RC pairs.

The local knowledge base also includes a document index with sample datasheet, BOM, schematic, and requirement records. `kb search` resolves exact `document_id`, `model_id`, and part-number queries before falling back to keyword search. `validate-kb` checks that indexed local metadata paths exist; verifies model-card hashes and semantic fields such as applicable circuits, required parameters, and outputs against `model.yaml`; and checks that each model package includes the required core assets: metadata, implementation, formula, review record, at least 3 examples, and at least 10 scenario tests.

Release input validation checks each requirement and parameter source `document_id` against the local knowledge-base document index, so source references must be registered before release. Requirements and parameters also need release-ready `review_status` values. It also checks that each circuit block `type` is supported by the selected model's `circuit_types` metadata before a release calculation can be approved.

Calculation output records each model's lifecycle status. Approved models produce `release_candidate` results; `draft` and `reviewing` models can only produce `not_for_release` trial results, and `blocked` models are rejected before execution.

Before a model runs, `calculate` validates the selected knowledge-base model card against the model metadata and source-file hashes. A stale or mismatched card stops execution with `model_preflight_failed`.

Supported engineering units are normalized before model execution, for example `mV` to `V`, `kohm` to `ohm`, `nF` to `F`, and `ms` to `s`. Conversion records are written to result traceability as `unit_conversions`.

`input-build` then writes:

- `examples/project_sample/work/wcca_input_draft.yaml`

If extracted requirements include `model_id`, `input-build` maps them into matching draft circuit blocks while keeping them `rule_extracted`.

`review-checklist` and `approve` write:

- `examples/project_sample/review/comments/review_checklist.md`
- `examples/project_sample/review/approvals/approval_record.md`

`package` writes `archive_manifest.json` with one SHA256 hash per archived file. `audit` checks input/result/model hashes, approval records, validation status, package contents, package member hashes against that manifest, and `model_trace.json` consistency with the traceability embedded in `results.json`.

Calculation output includes `parameter_sources.csv`, a reviewable source matrix for each input parameter with value, unit, source type, `document_id`, review status, and risk reason.

`wcca_results.xlsx` includes separate sheets for summary, calculation steps, traceability, risk items, parameter sources, requirements coverage, and unit conversions so engineers can review the same evidence without opening JSON.

`validate` recalculates Pass/Fail and `margin_min`/`margin_max` from the reported worst-case values and requirement limits, so tampered or inconsistent result summaries are blocked before approval.

`validate` also checks that every `risk_accepted` or `typical` input parameter has a matching `parameter_risk` entry in `risk_items`, so accepted risks cannot be silently dropped from the release evidence.

`validate` checks `requirements_coverage` rows inside `results.json`, and `audit` compares `requirements_coverage.csv` against those rows so the coverage matrix cannot drift from the approved result set.

`validate` also checks `parameter_sources` rows inside `results.json`, and `audit` compares `parameter_sources.csv` against those rows so parameter source evidence cannot drift from the approved input set.

Run tests:

```bash
python -m unittest discover
```
