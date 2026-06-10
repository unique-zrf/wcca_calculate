# WCCA 计算模型库与知识库接入规划方案

## 1. 方案定位

本文作为《WCCA 文档生成自动化规划方案》的补充方案，重点定义 WCCA 自动化系统中计算模型库的建设方式、知识库接入方式、模型调用边界以及工程师和 AI Agent 的使用流程。

本方案遵循以下总体原则：

- 计算模型库负责确定性工程计算。
- 知识库负责依据、说明、案例和审核记录检索。
- WCCA Core CLI 负责模型加载、输入校验、单位归一化、计算执行、结果输出和审计追溯。
- AI Agent 负责辅助识别、检索、编排、草稿生成和风险总结，但不得绕过 CLI 直接执行关键计算。
- 工程师负责关键参数确认、模型选择确认、风险接受和最终签核。

一句话边界：

> 模型库解决“怎么算”，知识库解决“为什么这么算、依据在哪里”，CLI 解决“受控地执行计算”，AI 解决“辅助理解和表达”。

## 2. 总体架构

推荐总体架构如下：

```text
AI Agent / 工程师
  -> 查询知识库，识别电路类型、候选模型、参数来源和风险
  -> 生成或确认 wcca_input.yaml
  -> 调用 WCCA Core CLI

WCCA Core CLI
  -> 校验输入参数、单位、来源和确认状态
  -> 按 model_id + model_version 加载计算模型
  -> 执行 Worst Case / RSS / Monte Carlo / SPICE 接口调用
  -> 输出 results.json、Excel 计算表和 traceability
  -> 执行 validate 和 report

知识库
  -> 保存模型卡片、公式说明、适用边界、历史案例、参数来源规则、审核记录
  -> 为 AI Agent 和工程师提供依据检索

计算模型库
  -> 保存可执行模型代码、模型元数据、示例和测试
  -> 不作为自然语言知识库直接检索执行
```

## 3. 计算模型库建设方案

### 3.1 建设方式

计算模型库按“电路类型”建设，项目只引用模型版本并提供结构化输入。模型不按项目复制，避免同一类电路在不同项目中出现公式分叉和审计困难。

推荐首批模型：

| 模型 ID | 电路类型 | Phase 1 是否建设 | 说明 |
| --- | --- | --- | --- |
| resistor_divider | 电阻分压 | 是 | 高频、低歧义，适合自动化 |
| ldo_power_rail | LDO 电源轨 | 是 | 电源 WCCA 高频场景 |
| comparator_threshold | 比较器阈值 | 是 | 阈值上下限和迟滞分析明确 |
| rc_delay | RC 延时 | 是 | 时间常数和阈值延时适合确定性计算 |
| adc_sampling_chain | ADC 采样链路 | 后续 | 涉及 ADC 误差、输入泄漏、采样保持等 |
| dcdc_feedback | DC/DC 反馈网络 | 后续 | 涉及纹波、补偿和瞬态条件 |
| op_amp_gain | 运放增益 | 后续 | 需考虑失调、偏置电流、开环增益等 |
| mosfet_switch_loss | MOSFET 开关损耗 | 后续 | 涉及功耗、热和驱动边界 |
| thermal_rise | 热设计 | 后续 | 需结合热阻、环境和功耗模型 |

### 3.2 模型五件套

每个计算模型上线前必须包含以下五类资产：

```text
wcca_models/
  resistor_divider/
    1.0.0/
      model.yaml
      implementation.py
      formula.md
      examples/
        basic.yaml
        worst_case.yaml
      tests/
        test_resistor_divider.py
```

各文件职责如下：

| 文件或目录 | 职责 |
| --- | --- |
| model.yaml | 模型 ID、版本、状态、输入输出、适用范围、审核信息 |
| implementation.py | 可执行计算实现，只能由 CLI 受控调用 |
| formula.md | 公式说明、适用边界、参数说明，可进入知识库 |
| examples/ | 示例输入输出，用于说明和回归 |
| tests/ | 单元测试和边界测试，用于模型上线验收 |

### 3.3 model.yaml 示例

```yaml
model_id: resistor_divider
model_name: Resistor Divider Worst Case Model
version: 1.0.0
status: approved
owner: hardware-wcca-team

kb_card_id: KB-MODEL-resistor_divider-1.0.0
formula_doc: formula.md
review_record: review_record.md

circuit_types:
  - resistor_divider
  - voltage_sampling_divider

inputs:
  - name: vin_min
    unit: V
    required: true
    source_required: true
  - name: vin_max
    unit: V
    required: true
    source_required: true
  - name: r_top
    unit: ohm
    required: true
    fields:
      - nominal
      - tolerance
      - tempco
      - aging
  - name: r_bottom
    unit: ohm
    required: true
    fields:
      - nominal
      - tolerance
      - tempco
      - aging

outputs:
  - name: vout_nominal
    unit: V
  - name: vout_worst_min
    unit: V
  - name: vout_worst_max
    unit: V
  - name: margin_min
    unit: "%"
  - name: margin_max
    unit: "%"
  - name: pass_fail
    unit: boolean

capabilities:
  supports_worst_case: true
  supports_rss: false
  supports_monte_carlo: false
  engineer_review_required: true

review:
  reviewers:
    - hardware_engineer
    - wcca_engineer
  approved_at: 2026-06-09
  approval_record: review_record.md
```

## 4. 模型生命周期与版本管理

### 4.1 生命周期状态

模型必须具备生命周期状态，只有 `approved` 模型可以进入正式 WCCA 报告。

| 状态 | 说明 | 正式报告是否允许 |
| --- | --- | --- |
| draft | 草稿，只能开发和试算 | 否 |
| reviewing | 等待工程审核 | 否 |
| approved | 已批准，可用于正式项目 | 是 |
| deprecated | 不推荐新项目使用，但可复现历史项目 | 条件允许 |
| blocked | 存在严重问题，禁止调用 | 否 |

CLI 执行规则：

- `draft` 和 `reviewing`：只能试算，结果必须标记为 `not_for_release`。
- `approved`：允许进入正式报告。
- `deprecated`：允许复现历史项目，新项目默认警告或拦截。
- `blocked`：禁止计算，除非管理员审计模式查看历史记录。

### 4.2 版本规则

已批准模型版本不得覆盖。任何公式、边界条件、Pass/Fail 规则或输出字段变化，都必须发布新版本。

推荐版本规则：

| 版本变化 | 场景 |
| --- | --- |
| 1.0.0 -> 1.0.1 | 文档、示例、注释修正，不改变结果 |
| 1.0.0 -> 1.1.0 | 新增可选输入或输出，默认行为不变 |
| 1.0.0 -> 2.0.0 | 公式、边界条件、默认规则或 Pass/Fail 逻辑改变 |

历史项目必须锁定模型版本：

```yaml
model_id: resistor_divider
model_version: 1.0.0
```

模型升级后必须执行历史样例回归。如果结果发生变化，必须生成 `migration_note.md`，说明影响范围和迁移建议。

## 5. 知识库接入方案

### 5.1 入库内容

知识库只保存说明性、依据性、审计性材料，不保存可执行模型代码。

建议入库内容：

- `formula.md`
- `model.yaml` 摘要
- `examples/*.yaml` 的输入输出说明
- 测试覆盖说明
- `review_record.md`
- 历史项目调用案例
- 常见误用和适用边界
- 参数来源规则
- 评审问题和风险接受记录

不建议入库内容：

- `implementation.py`
- 测试代码全文
- 临时调试数据
- 未审核模型草稿
- 项目敏感 BOM
- 客户敏感资料

### 5.2 模型卡片

知识库中每个模型版本应形成一张模型卡片。

```yaml
kb_card_id: KB-MODEL-resistor_divider-1.0.0
doc_type: calculation_model_card
model_id: resistor_divider
model_version: 1.0.0
status: approved

applicable_circuits:
  - resistor_divider
  - voltage_sampling_divider

required_parameters:
  - vin_min
  - vin_max
  - r_top.nominal
  - r_top.tolerance
  - r_bottom.nominal
  - r_bottom.tolerance

outputs:
  - vout_nominal
  - vout_worst_min
  - vout_worst_max
  - margin_min
  - margin_max
  - pass_fail

limitations:
  - 不适用于高频分压网络
  - 不包含 ADC 输入泄漏电流影响
  - 不包含 PCB 污染或漏电路径

source_files:
  - path: wcca_models/resistor_divider/1.0.0/model.yaml
    sha256: "<model_yaml_sha256>"
  - path: wcca_models/resistor_divider/1.0.0/formula.md
    sha256: "<formula_md_sha256>"
  - path: wcca_models/resistor_divider/1.0.0/review_record.md
    sha256: "<review_record_sha256>"

review_status: approved
```

### 5.3 模型库与知识库绑定字段

模型库与知识库必须通过稳定字段绑定，不得仅依赖文件名或自然语言标题。

推荐绑定字段：

- `model_id`
- `model_version`
- `kb_card_id`
- `source_file_hash`

AI Agent 检索知识库后，只能返回明确模型坐标：

```text
推荐使用 model_id=resistor_divider, model_version=1.0.0。
```

CLI 再根据该坐标加载模型，并校验模型文件 hash、状态和版本是否匹配。

## 6. 第一版知识库形态

第一版建议采用本地文件夹知识库和 YAML 索引，后续再升级到 RAGFlow、企业知识库或向量数据库。

推荐目录结构：

```text
wcca_knowledge_base/
  datasheets/
    vendor/
      part_number/
        document.pdf
        metadata.yaml
  standards/
    company_derating_standard/
      document.docx
      metadata.yaml
  model_cards/
    KB-MODEL-resistor_divider-1.0.0.yaml
    KB-MODEL-ldo_power_rail-1.0.0.yaml
  historical_cases/
    project_x/
      case_summary.md
      calculation_reference.yaml
  review_notes/
    checklist.md
    common_issues.md
  index/
    documents_index.yaml
    model_cards_index.yaml
    parameter_rules_index.yaml
```

第一版支持的检索方式：

- `part_number` 精确匹配
- `model_id` 精确匹配
- `document_id` 精确匹配
- 参数来源规则查找
- 简单关键词检索

升级路线：

```text
本地文件夹知识库
  -> 文档解析和分块
  -> 混合检索
  -> RAGFlow / 企业知识库
  -> 权限、版本、审计和审批流
```

## 7. 模型调用边界

AI Agent 不得直接调用模型函数，只能通过 WCCA Core CLI 或受控 API 发起计算。

禁止方式：

```python
from wcca_models.resistor_divider.implementation import calculate
calculate(...)
```

推荐方式：

```bash
wcca calculate \
  --input ./work/wcca_input.yaml \
  --output ./output/calculation/ \
  --trace ./output/traceability/model_trace.json
```

原因：

- 避免绕过单位归一化。
- 避免绕过参数来源检查。
- 避免绕过模型版本锁定。
- 避免绕过 Typical 风险检查。
- 避免绕过工程师确认状态检查。
- 保证审计日志完整。

## 8. 项目输入规范

项目通过 `wcca_input.yaml` 调用模型。关键参数必须包含来源和确认状态。

示例：

```yaml
project:
  name: MotorController
  document_type: WCCA

circuit_blocks:
  - id: ADC_IN_01
    name: ADC Input Divider
    type: voltage_sampling_divider

    selected_model:
      model_id: resistor_divider
      model_version: 1.0.0
      selection_status: engineer_confirmed
      confirmed_by: Zhang

    requirements:
      - id: REQ-ADC-001
        description: ADC input voltage shall remain within allowed range.
        min_value: 0.45
        max_value: 0.55
        unit: V

    inputs:
      vin_min:
        value: 4.75
        unit: V
        parameter_type: min
        source:
          type: requirement
          document_id: REQ-MC-001
          section: Power Input
        review_status: confirmed

      vin_max:
        value: 5.25
        unit: V
        parameter_type: max
        source:
          type: requirement
          document_id: REQ-MC-001
          section: Power Input
        review_status: confirmed

      r_top:
        nominal:
          value: 100000
          unit: ohm
          parameter_type: nominal
          source:
            type: bom
            document_id: BOM-2026-001
            field: Resistance
          review_status: confirmed
        tolerance:
          value: 1
          unit: "%"
          parameter_type: tolerance
          source:
            type: datasheet
            document_id: DS-RES-001
            page: 3
            table: Electrical Characteristics
          review_status: confirmed

      r_bottom:
        nominal:
          value: 10000
          unit: ohm
          parameter_type: nominal
          source:
            type: bom
            document_id: BOM-2026-001
            field: Resistance
          review_status: confirmed
        tolerance:
          value: 1
          unit: "%"
          parameter_type: tolerance
          source:
            type: datasheet
            document_id: DS-RES-001
            page: 3
            table: Electrical Characteristics
          review_status: confirmed
```

参数确认状态建议：

| 状态 | 说明 | 正式发布 |
| --- | --- | --- |
| missing | 缺失 | 否 |
| ai_extracted | AI 提取但未确认 | 否 |
| rule_extracted | 规则提取但未确认 | 否 |
| confirmed | 工程师已确认 | 是 |
| risk_accepted | 有风险但工程师接受 | 是，必须输出风险项 |
| not_applicable | 不适用 | 条件允许 |

Typical 值不得直接作为 Worst Case 使用。若只能获得 Typical，必须标记为风险：

```yaml
parameter_type: typical
review_status: risk_accepted
risk_reason: Only typical value available; engineer accepted for this analysis.
```

## 9. 模型选择策略

知识库检索到多个候选模型时，应按风险等级处理。

| 场景 | 策略 |
| --- | --- |
| 电路类型明确、模型唯一、参数完整、风险低 | 可自动选择 |
| 多个模型都可能适用 | AI 推荐，工程师确认 |
| 高风险或边界复杂 | 工程师确认 |
| 无匹配模型 | 手动分析或新建模型 |

候选模型记录示例：

```yaml
circuit_block_id: ADC_IN_01
detected_type: voltage_sampling_divider
candidates:
  - model_id: resistor_divider
    model_version: 1.0.0
    confidence: 0.72
    limitation: Does not include ADC input leakage or sampling capacitor loading.
  - model_id: adc_sampling_chain
    model_version: 1.0.0
    confidence: 0.91
    reason: Includes divider tolerance, ADC reference error, quantization error, and input leakage.
selected_model:
  model_id: adc_sampling_chain
  model_version: 1.0.0
selection_status: engineer_confirmed
confirmed_by: Zhang
```

## 10. 计算结果输出规范

计算结果不能只输出最终 Pass/Fail，必须包含摘要结果、计算步骤和追溯信息。

推荐结构：

```yaml
circuit_block_id: PWR_3V3
model_id: ldo_power_rail
model_version: 1.0.0

summary_result:
  nominal: 3.3
  worst_min: 3.234
  worst_max: 3.366
  requirement_min: 3.135
  requirement_max: 3.465
  margin_min: 3.16
  margin_max: 2.86
  pass_fail: pass

calculation_steps:
  - step: output_accuracy_min
    formula: Vout_nominal * (1 - accuracy_max)
    inputs:
      Vout_nominal: 3.3
      accuracy_max: 0.02
    result: 3.234
    unit: V

traceability:
  input_parameters:
    - name: output_accuracy
      source: datasheet page 5 table Electrical Characteristics
      review_status: confirmed
  model_hash: sha256:<model_hash>
  input_version: sha256:<input_hash>
  calculation_tool_version: 0.3.0
  calculated_at: 2026-06-09T10:30:00+08:00
```

输出物建议：

- `results.json`：完整结构化结果。
- `wcca_results.xlsx`：工程师可审阅的计算表。
- `model_trace.json`：模型、输入、来源、hash、执行日志。
- `risk_items.md` 或 `risk_items.xlsx`：风险项清单。
- `requirements_coverage.csv`：需求覆盖矩阵。

## 11. 使用流程

### 11.1 工程师使用流程

```text
1. 准备项目资料：BOM、网表、需求、datasheet、规范、模板。
2. 执行 ingest，生成资料索引。
3. AI Agent 辅助识别电路块和候选模型。
4. 工程师确认模型选择。
5. AI Agent 或规则生成 wcca_input.yaml 草稿。
6. 工程师确认关键参数来源和 review_status。
7. 执行 validate-input。
8. 执行 calculate。
9. 执行 validate，检查单位、来源、Typical、数值一致性和 Pass/Fail。
10. 执行 report，生成报告草稿。
11. 工程师 Review 和签核。
12. 执行 package，生成归档包。
```

### 11.2 CLI 使用示例

```bash
wcca model list --status approved
wcca model show resistor_divider --version 1.0.0
wcca validate-input --input ./work/wcca_input.yaml
wcca calculate --input ./work/wcca_input.yaml --output ./output/calculation/
wcca validate --input ./work/wcca_input.yaml --results ./output/calculation/results.json
wcca report --input ./work/wcca_input.yaml --results ./output/calculation/results.json --output ./output/report/
wcca package --project ./ --output ./release/wcca_package.zip
```

### 11.3 AI Agent 使用边界

AI Agent 可以负责：

- 识别电路可能适用的模型。
- 检索知识库中的模型卡片、参数来源规则和历史案例。
- 提示缺失参数。
- 辅助生成 `wcca_input.yaml` 草稿。
- 解释计算结果和低裕量风险。
- 生成报告草稿。
- 生成 Review checklist。

AI Agent 不得负责：

- 无依据生成关键参数。
- 绕过 CLI 直接调用模型函数。
- 直接给出未经计算验证的 Pass/Fail。
- 自动接受 Typical 值风险。
- 替代工程师确认边界条件。
- 替代正式签核。

## 12. 推荐仓库结构

初期建议 CLI、模型库、知识库卡片和模板放在同一仓库内，模块化管理；成熟后再拆分独立仓库。

```text
wcca-automation/
  wcca_cli/
    commands/
    validation/
    report/
    package/

  wcca_models/
    registry.yaml
    resistor_divider/
      1.0.0/
        model.yaml
        implementation.py
        formula.md
        review_record.md
        examples/
        tests/
    ldo_power_rail/
      1.0.0/
    comparator_threshold/
      1.0.0/
    rc_delay/
      1.0.0/

  wcca_knowledge_base/
    model_cards/
    datasheets/
    standards/
    historical_cases/
    review_notes/
    index/

  templates/
    company_wcca_template.docx
    calculation_table_template.xlsx

  tests/
    regression_cases/
    unit/

  examples/
    project_sample/
      input/
      work/
      output/
```

未来成熟后可拆分为：

```text
wcca-core-cli
wcca-models
wcca-knowledge-base
wcca-templates
wcca-agents
```

## 13. Phase 1 交付范围

Phase 1 建议只覆盖 4 个模型：

- `resistor_divider`
- `ldo_power_rail`
- `comparator_threshold`
- `rc_delay`

每个模型验收标准：

- 包含 `model.yaml + implementation.py + formula.md + examples + tests` 五件套。
- 至少 3 个示例。
- 至少 10 条单元测试。
- 至少跑过 1 个历史项目片段。
- 有工程师 `review_record.md`。
- 模型状态为 `approved` 后才能进入正式报告。
- CLI 能输出 `summary_result + calculation_steps + traceability`。
- 知识库中有对应模型卡片。
- 模型卡片与模型文件 hash 一致。

Phase 1 系统验收标准：

- 支持 `wcca_input.yaml` 输入。
- 支持模型列表和模型详情查看。
- 支持输入字段、单位、来源、确认状态校验。
- 支持执行 4 类模型计算。
- 支持输出 JSON 和 Excel 结果。
- 支持 Typical 风险检查。
- 支持 Pass/Fail 与 Margin 一致性检查。
- 支持生成参数来源清单和需求覆盖矩阵。
- 支持报告草稿生成。
- 支持归档包生成。

## 14. 风险控制

### 14.1 AI 误提取参数

控制措施：

- 关键参数必须有 `source`。
- 关键参数必须有 `review_status`。
- `ai_extracted` 参数只能试算，不能正式发布。
- Typical 值必须标记风险。

### 14.2 模型公式或边界错误

控制措施：

- 模型必须有版本号。
- 模型必须有单元测试。
- 模型必须有工程师审核记录。
- 已 approved 的模型版本不得覆盖。
- 模型升级必须跑历史回归。

### 14.3 知识库说明与实际执行模型不一致

控制措施：

- 使用 `model_id + model_version + kb_card_id + source_file_hash` 绑定。
- CLI 执行时校验模型状态和 hash。
- 知识库卡片更新必须与模型版本同步。

### 14.4 AI 绕过 CLI 直接计算

控制措施：

- AI Agent 只能调用 CLI/API。
- `implementation.py` 不进入知识库。
- 计算结果必须有 CLI 执行日志。
- 报告关键数值只能来自计算结果文件。

### 14.5 自动化过度替代人工判断

控制措施：

- 多候选模型必须工程师确认。
- 高风险参数必须工程师确认或风险接受。
- `risk_accepted` 必须进入风险项清单。
- 正式报告必须工程师签核。

## 15. 最终建议

WCCA 计算模型库不应建设成单纯的公式文档库，也不应被 AI Agent 直接调用为普通函数库。它应作为受版本、测试、审核和审计控制的工程计算资产。

推荐最终落地方式为：

```text
计算模型库：保存可执行模型和测试，按电路类型与版本管理。
知识库：保存模型卡片、公式说明、适用范围、审核记录和历史案例。
WCCA Core CLI：统一执行模型调用、输入校验、单位归一化、计算、校验和追溯。
AI Agent：辅助检索、识别、编排、草稿生成和风险总结。
工程师：确认参数、确认模型、接受风险并签核结论。
```

核心结论：

> 第一版应以 `wcca_input.yaml + WCCA Core CLI + 本地文件夹知识库 + 四个基础模型` 为落地核心，先建立可复现、可追溯、可审计的最小闭环，再逐步扩展 RAG、Subagent、Web 平台和企业系统集成。
