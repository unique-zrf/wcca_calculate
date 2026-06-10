# WCCA Implementation Status

This document maps the current implementation to `WCCA计算模型库与知识库接入规划方案.md`.

## Implemented Phase 1 Scope

| Requirement | Evidence |
| --- | --- |
| WCCA Core CLI | `wcca_cli/cli.py` |
| Project initialization | `python -m wcca_cli init --project <path> --name <name>` |
| Input file indexing | `python -m wcca_cli ingest --project <path>` |
| BOM extraction | `python -m wcca_cli extract --project <path>` |
| Netlist extraction | `python -m wcca_cli extract --project <path>` writes `work/extracted/netlist.yaml` |
| Requirement extraction | `python -m wcca_cli extract --project <path>` writes `work/extracted/requirements.yaml` |
| Parameter normalization | `python -m wcca_cli normalize --project <path>` |
| WCCA input draft generation | `python -m wcca_cli input-build --project <path>` |
| Model list/show | `python -m wcca_cli model list`, `model show` |
| Model metadata diff | `python -m wcca_cli model diff <model_id> --from-version <v1> --to-version <v2>` |
| Knowledge card/hash, semantic binding, and model asset validation | `python -m wcca_cli validate-kb` checks card hashes, card semantic fields, document metadata paths, required model package assets, and per-model test counts |
| Local knowledge search | `python -m wcca_cli kb search <query>` |
| Local knowledge item show | `python -m wcca_cli kb show <id_or_path>` |
| Document and part-number knowledge lookup | `wcca_knowledge_base/index/documents_index.yaml` plus `python -m wcca_cli kb search <document_id_or_part_number>` |
| Release input validation | `python -m wcca_cli validate-input --input <file> --release` checks model, requirement, and parameter status; selected-model circuit type applicability; and known source `document_id` values |
| Controlled unit normalization | `wcca_cli/units.py` converts supported engineering units before model execution and records `unit_conversions` |
| Deterministic calculation | `python -m wcca_cli calculate --input <file> --output <dir>` |
| Calculation preflight model-card binding validation | Selected model `kb_card_id`, status, version, and source-file hashes are checked before execution |
| Model lifecycle execution gates | `blocked` models are rejected; `draft`/`reviewing` models produce `not_for_release`; `deprecated` models produce a warning |
| Parameter source matrix output | `output/calculation/parameter_sources.csv` and Excel `parameter_sources` sheet |
| Result validation | `python -m wcca_cli validate --input <file> --results <results.json>` recalculates Pass/Fail and margins, verifies accepted-risk parameter coverage, validates requirements coverage rows, and validates parameter source rows |
| Report draft generation | `python -m wcca_cli report --input <file> --results <results.json> --output <dir>` |
| Review checklist generation | `python -m wcca_cli review-checklist --input <file> --results <results.json> --output <dir>` |
| Approval record generation | `python -m wcca_cli approve --input <file> --results <results.json> --output <dir> --reviewer <name> --decision approved` |
| Archive package generation | `python -m wcca_cli package --project <dir> --output <zip>` writes `archive_manifest.json` with per-file SHA256 |
| Release audit | `python -m wcca_cli audit --project <dir>` validates required files, model trace/result consistency, package contents, and archive manifest hashes |
| Installable package includes model and knowledge assets | `pyproject.toml` package data for `wcca_models` and `wcca_knowledge_base` |

## Implemented Models

| Model | Version | Status | Evidence |
| --- | --- | --- | --- |
| `resistor_divider` | 1.0.0 | approved | `wcca_models/resistor_divider/1.0.0/` |
| `ldo_power_rail` | 1.0.0 | approved | `wcca_models/ldo_power_rail/1.0.0/` |
| `comparator_threshold` | 1.0.0 | approved | `wcca_models/comparator_threshold/1.0.0/` |
| `rc_delay` | 1.0.0 | approved | `wcca_models/rc_delay/1.0.0/` |

Each model includes the required Phase 1 model package assets:

- `model.yaml`
- `implementation.py`
- `formula.md`
- `review_record.md`
- `examples/`
- `tests/`

Each model has at least 3 example files and at least 10 scenario test cases in its own `wcca_models/<model_id>/<version>/tests/` package. The repository-level `tests/test_model_scenarios.py` keeps an additional cross-model regression view.

## Knowledge Base

Implemented local-file knowledge base:

- `wcca_knowledge_base/model_cards/`
- `wcca_knowledge_base/index/`
- `wcca_knowledge_base/review_notes/`

Model cards bind:

- `model_id`
- `model_version`
- `kb_card_id`
- source file `sha256`

Executable code files are not listed in model cards.

Local knowledge search currently covers:

- model cards
- document indexes by `document_id`, `doc_type`, `part_numbers`, keywords, and summary
- parameter rules
- review notes

Exact `document_id`, `model_id`, and part-number queries are resolved before keyword search to avoid substring false positives such as `DS-RES` matching `DS-RESET`.

`validate-kb` validates model-card hashes and semantic binding fields against `model.yaml`, including `applicable_circuits` vs. `circuit_types`, `required_parameters` vs. required model inputs, and `outputs` vs. model output names. It also validates local document-index metadata paths and each model package's required assets: `model.yaml`, `implementation.py`, `formula.md`, `review_record.md`, at least 3 example YAML files, and at least 10 `test_...` scenario cases under `tests/test_*.py`.

Release input validation checks every requirement and required parameter source `document_id` against `wcca_knowledge_base/index/documents_index.yaml`, so misspelled or unregistered source documents cannot enter release calculations. Requirement and parameter `review_status` values must be release-ready before approval. It also verifies each circuit block `type` against the selected model's `circuit_types` list, so an approved model cannot be released against an unsupported circuit class.

Calculation results include per-block `model_status` and `release_status`. Release validation requires `release_status=release_candidate`, so trial calculations from `draft` or `reviewing` models cannot be approved or audited as release results.

Before executing a model, `calculate` validates the selected model card binding and source-file hashes. If the knowledge-base card no longer matches the model files, calculation stops with `model_preflight_failed`.

Before executing a model, `calculate` also normalizes supported engineering units to model units, such as `mV` to `V`, `kohm` to `ohm`, `nF` to `F`, and `ms` to `s`. Unit conversions are recorded in each result's `traceability.unit_conversions` list and at the calculation root as `unit_conversions`.

Release packages include an `archive_manifest.json` with one SHA256 hash per archived file. `audit` recalculates package member hashes and fails if package contents no longer match the manifest.

`audit` also compares `output/calculation/model_trace.json` against the per-result traceability embedded in `results.json`, including model coordinates, model/release status, and traceability hashes, so trace evidence cannot drift from the approved calculation results.

Requirement coverage is validated in two places: `validate` checks the `requirements_coverage` rows embedded in `results.json` against the input requirements and result summaries, and `audit` checks `requirements_coverage.csv` against `results.json`.

Parameter source coverage is also validated in two places: `validate` checks `parameter_sources` rows embedded in `results.json` against the normalized input parameter values and source metadata, and `audit` checks `parameter_sources.csv` against `results.json`.

## Sample Project

Sample input:

- `examples/project_sample/work/wcca_input.yaml`
- `examples/project_sample/input/bom/sample_bom.csv`
- `examples/project_sample/input/netlist/sample_netlist.csv`
- `examples/project_sample/input/requirements/requirements.csv`

Generated sample outputs:

- `examples/project_sample/work/input_index.yaml`
- `examples/project_sample/work/extracted/components.yaml`
- `examples/project_sample/work/extracted/parameter_draft.yaml`
- `examples/project_sample/work/extracted/netlist.yaml`
- `examples/project_sample/work/extracted/requirements.yaml`
- `examples/project_sample/work/normalized/parameters.yaml`
- `examples/project_sample/work/normalized/model_candidates.yaml`
- `examples/project_sample/work/wcca_input_draft.yaml`
- `examples/project_sample/output/calculation/results.json`
- `examples/project_sample/output/calculation/model_trace.json`
- `examples/project_sample/output/calculation/wcca_results.xlsx`
- `examples/project_sample/output/calculation/risk_items.md`
- `examples/project_sample/output/calculation/parameter_sources.csv`
- `examples/project_sample/output/calculation/requirements_coverage.csv`
- `examples/project_sample/output/report/wcca_report.md`
- `examples/project_sample/review/comments/review_checklist.md`
- `examples/project_sample/review/approvals/approval_record.md`
- `examples/project_sample/release/wcca_package.zip`

`wcca_results.xlsx` includes reviewable sheets for `summary`, `calculation_steps`, `traceability`, `risk_items`, `parameter_sources`, `requirements_coverage`, and `unit_conversions`.

## Verification Commands

Latest verified commands:

```bash
python -m unittest discover
python -m pip wheel . --no-deps --no-build-isolation -w tmp_wheel_check
python -m wcca_cli validate-kb
python -m wcca_cli kb search "RC0402FR-07100KL"
python -m wcca_cli kb show DS-LDO
python -m wcca_cli kb search "typical worst case"
python -m wcca_cli kb show KB-MODEL-resistor_divider-1.0.0
python -m wcca_cli ingest --project examples/project_sample
python -m wcca_cli extract --project examples/project_sample
python -m wcca_cli normalize --project examples/project_sample
python -m wcca_cli input-build --project examples/project_sample
python -m wcca_cli validate-input --input examples/project_sample/work/wcca_input.yaml --release
python -m wcca_cli calculate --input examples/project_sample/work/wcca_input.yaml --output examples/project_sample/output/calculation
python -m wcca_cli validate --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json
python -m wcca_cli report --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/output/report
python -m wcca_cli review-checklist --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/review/comments
python -m wcca_cli approve --input examples/project_sample/work/wcca_input.yaml --results examples/project_sample/output/calculation/results.json --output examples/project_sample/review/approvals --reviewer sample_engineer --decision approved
python -m wcca_cli package --project examples/project_sample --output examples/project_sample/release/wcca_package.zip
python -m wcca_cli audit --project examples/project_sample
```

## Remaining Future Scope

These items are intentionally not complete in the current Phase 1 implementation:

- Full BOM parser.
- BOM extraction currently supports structured CSV/XLSX rows and basic resistor/capacitor value parsing; full enterprise BOM normalization remains future work.
- Netlist extraction currently supports simple CSV/text connection lists and generates topology hints; full EDA netlist parsing remains future work.
- Requirement extraction currently supports structured CSV/XLSX requirement tables with model_id, min, max, and unit.
- Normalized BOM-derived parameters remain `rule_extracted` and trial-only until an engineer confirms them.
- Generated WCCA input drafts intentionally keep missing requirements, boundary conditions, datasheet parameters, and model selections unconfirmed; release validation blocks these drafts until engineering completion.
- Approval records are only generated for `approved` decisions when release input validation and result validation pass.
- Release audit checks required files, release validation, result validation, model/input hash traceability, model trace/result consistency, approval hashes, package contents, and archive manifest hashes.
- Automatic circuit-block detection beyond simple topology hints.
- Datasheet PDF extraction.
- RAGFlow/vector database integration.
- AI Agent/Subagent orchestration.
- SPICE integration.
- Word/PDF report generation.
- Web UI, approval workflow, permissions, PLM/ERP/EDA integration.
- Additional Phase 2+ models such as `adc_sampling_chain`, `dcdc_feedback`, `op_amp_gain`, `mosfet_switch_loss`, and `thermal_rise`.
