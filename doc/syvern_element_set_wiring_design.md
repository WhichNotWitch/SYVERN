# SYVERN 元素集打通 设计与开发文档

> **SYVERN** = *SysML V2 EValuation & Reward eNgine*
> 文档级别:施工级设计 + 开发说明(纯仓内重构)。承接 HLD / LLD / 《阶段二生产化设计》(`syvern_phase2_design.md`)。
> 定位:本改造是 **H7(接真 Pilot 适配器)的隐藏前置**。它不依赖任何外部后端,可在 stub 阶段独立完成、独立验收;完成后接真后端时下游零改动即可生效。
> 约定:文中 `parse_result`、`match_structural`、`evaluate_veto` 等符号均指现有仓库代码;签名为设计基线。

---

## 1. 背景与问题

### 1.1 一句话问题
解析器(无论 stub 还是未来的真 Pilot)产出的**元素集**(`ParseResult.element_summary`)在 pipeline 里被丢弃,下游所有需要元素集的环节各自对**原始文本**重跑一条正则 `extract_element_summary(text)`。因此即便接上真 Pilot,T1 结构指标、退化否决、枚举检测、IPT **仍跑在玩具正则上**。

### 1.2 实测佐证
对 `part def Vehicle { ... }`,正则把关键字 `def` 当成了元素名:

```
extract_element_summary("part def Vehicle { attribute mass : Real; part engine : Engine; }")
  → [("part","def"), ("attribute","mass"), ("part","engine")]      # "Vehicle" 丢失,"def" 误判
```

结果:语法损坏的代码与合法代码拿到相同奖励(0.900),系统实际验证能力为零。

### 1.3 设计目标
让"谁解析、谁产出元素集",该元素集即作为**单一可信来源(single source of truth)**流到所有消费方;**消灭下游用正则重抽元素的旁路**。

### 1.4 为何先做这一步(与 H7 的关系)
- 接真 Pilot 负责"产出正确元素集";本改造负责"让正确元素集真正被用上"。**只做前者不做后者 = 白接。**
- 本改造纯 Python、有测试护栏,可在 stub 阶段完成;stub 的 `parse()` 本就返回正则结果,所以打通后 stub 路径行为不变,接真后端时自动切换为真元素集。

---

## 2. 范围

### 2.1 在范围内
- `ParseResult.element_summary` 在 pipeline 内的捕获与传递。
- 四个消费方改为接收元素集:结构匹配、退化否决、抗作弊规则、IPT。
- 相应单元测试更新 + 新增"合法 vs 语法损坏"红线回归用例。

### 2.2 不在范围内
- 真 Pilot/HTTP 服务实现(H7 主体,见 `syvern_phase2_design.md` §2)。
- 元素抽取算法本身的升级(仍由各适配器的 `parse()` 负责;stub 继续用正则,真后端用 AST 遍历)。
- 结构匹配策略、IPT 语义、奖励公式的任何改动(保持冻结)。

---

## 3. 现状分析

### 3.1 当前数据流(断的)

```
self.pilot.parse(text) ─▶ parse_result
                            ├─ .ok / .errors      ──▶ 用于 stage 判决 ✅
                            └─ .element_summary    ──✗ 被丢弃

text(原始文本) ─▶ extract_element_summary(text) ─┬─▶ 结构匹配  (pipeline.py:217)
                                                 ├─▶ 退化否决  (veto.py:26)
                                                 ├─▶ 枚举/规则 (rules.py:34)
                                                 └─▶ IPT       (ipt.py:9,32)
```

### 3.2 四个消费方与精确位置

| 消费方 | 位置 | 现状 | 除元素外还需要 |
|---|---|---|---|
| 结构匹配 | [pipeline.py:217](../src/syvern/pipeline.py) | `match_structural(extract_element_summary(text), ...)` | — |
| 退化否决 | [veto.py:26](../src/syvern/veto.py) | `len(extract_element_summary(text)) < min_elements` | `token_count(text)` |
| 抗作弊规则 | [rules.py:34](../src/syvern/rules.py) | `elements = extract_element_summary(text)` | `normalize_ws(text)`(filler/重复检测) |
| IPT | [ipt.py:9,32](../src/syvern/ipt.py) | 对原文与每条扰动各跑正则 | 每条扰动需**独立解析** |

关键观察:
- `match_structural` 的签名**已经接收元素集**([structural.py:154](../src/syvern/structural.py)),只是调用方传了正则结果——改动最小。
- `rules` / `veto` **同时需要 text 与元素集**(text 用于正则类检测,元素集用于结构类检测)。
- IPT 的扰动是**另一段文本**,必须用同一权威解析器单独解析,不能复用主文本的元素集——这是本改造最需要想清楚的一处。

---

## 4. 目标设计

### 4.1 目标数据流(打通后)

```
self.pilot.parse(text) ─▶ parse_result.element_summary ─┬─▶ 结构匹配
                                                        ├─▶ 退化否决
                                                        ├─▶ 枚举/规则
                                                        └─▶ IPT(原文元素)
self.pilot.parse(perturb_i).element_summary ───────────▶ IPT(扰动元素)
                       (单一可信来源:解析器)
```

### 4.2 核心原则
1. **解析器是元素集唯一来源**:pipeline 内任何需要元素集的地方,都来自某次 `self.pilot.parse(...).element_summary`,不再调用 `extract_element_summary`。
2. **text 与元素集解耦传递**:消费方需要文本就显式收 `text`,需要元素就显式收 `elements`,二者来源分明。
3. **IPT 由 pipeline 预解析扰动**:pipeline 负责把每条扰动喂给解析器,把元素集传入 `evaluate_ipt`;IPT 模块本身不再认识 `extract_element_summary`,变为纯函数。
4. **stub 兼容**:`extract_element_summary` 保留为 stub 适配器 `parse()` 的内部实现([stub.py:47](../src/syvern/adapters/stub.py)),不再被业务模块直接 import。

---

## 5. 详细改造

### 5.1 pipeline:捕获并传递元素集

`validate()` 已持有 `parse_result`([pipeline.py:65](../src/syvern/pipeline.py));新增一个内部辅助,统一从解析器取元素集:

```python
def _elements(self, text: str) -> list[ElementSummary]:
    return self.pilot.parse(text).element_summary
```

- 主文本:复用已有的 `parse_result.element_summary`,随 stage 一路传入 `_finish()`(`_finish` 当前只收 `text`,需加 `elements` 形参)。
- 注意:`parse()` 已被调用过一次,**不要重复解析主文本**;把 `parse_result` 或其 `element_summary` 透传即可。

### 5.2 结构匹配(改动最小)

```python
# pipeline.py  _finish 内
- structural = match_structural(extract_element_summary(text), reference, self.settings, soft_matcher=self.structural_matcher)
+ structural = match_structural(elements, reference, self.settings, soft_matcher=self.structural_matcher)
```
`match_structural` 签名不变。

### 5.3 退化否决

```python
# veto.py
- def evaluate_veto(*, text, settings, semantic_path_passed, parser_agreement, violations):
+ def evaluate_veto(*, text, elements, settings, semantic_path_passed, parser_agreement, violations):
      ...
      if semantic_path_passed:
          if token_count(text) < settings.min_tokens:            # 仍用 text
              return VetoSummary(triggered=True, reason="degenerate_output")
-         if len(extract_element_summary(text)) < settings.min_elements:
+         if len(elements) < settings.min_elements:              # 改用传入元素集
              return VetoSummary(triggered=True, reason="degenerate_output")
```
移除 `from syvern.adapters.stub import extract_element_summary`。

### 5.4 抗作弊规则

```python
# rules.py
- def evaluate_rules(text, settings) -> list[Violation]:
+ def evaluate_rules(text, elements, settings) -> list[Violation]:
      normalized = normalize_ws(text).lower()        # filler/重复:仍用 text
-     elements = extract_element_summary(text)
      ...                                            # 占位名/枚举:改用传入 elements
```
调用方 [pipeline.py:129](../src/syvern/pipeline.py):`evaluate_rules(text, elements, self.settings)`。移除对 `extract_element_summary` 的 import。

### 5.5 IPT(重点:扰动需独立解析)

IPT 改为纯函数,接收**已解析的元素集**,由 pipeline 负责解析扰动:

```python
# ipt.py
def evaluate_ipt(
    *,
    original_elements: list[ElementSummary],
    perturbation_element_sets: list[list[ElementSummary]],
    settings: SyvernSettings,
) -> bool | None:
    if not perturbation_element_sets or not original_elements:
        return None
    reference = {"elements": [{"type": e.type, "qualified_name": e.qualified_name}
                             for e in original_elements]}
    for perturbed in perturbation_element_sets:
        if match_structural(perturbed, reference, settings).f1 < settings.ipt_threshold:
            return False
    return True
```

```python
# pipeline.py  _finish 内(扰动用同一权威解析器逐条解析)
if ipt_evaluated:
    robustness = RobustnessSummary(
        ipt_consistent=evaluate_ipt(
            original_elements=elements,
            perturbation_element_sets=[self._elements(p) for p in perturbations],
            settings=self.settings,
        )
    )
```
`ipt.py` 移除 `from syvern.adapters.stub import extract_element_summary`。

> 设计权衡:也可把"解析函数"作为回调注入 `evaluate_ipt`。本文选择"pipeline 预解析、IPT 收纯数据",理由是 IPT 单测更易构造(直接喂元素集),且符合原则 3。

---

## 6. 接口契约变更汇总

| 模块 | 旧签名 | 新签名 |
|---|---|---|
| `pipeline._finish` | `_finish(*, text, mode, stage, ...)` | `_finish(*, text, elements, mode, stage, ...)` |
| `structural.match_structural` | (不变) | (不变,仅调用方改) |
| `veto.evaluate_veto` | `(*, text, settings, semantic_path_passed, parser_agreement, violations)` | `(*, text, elements, settings, semantic_path_passed, parser_agreement, violations)` |
| `rules.evaluate_rules` | `(text, settings)` | `(text, elements, settings)` |
| `ipt.evaluate_ipt` | `(*, original_text, perturbations, settings)` | `(*, original_elements, perturbation_element_sets, settings)` |

**不再被业务模块 import 的符号**:`extract_element_summary`(仅留在 `stub.py` 内部供 stub 的 `parse()` 使用)。

---

## 7. 兼容性与适配器边界

- **行为等价(stub 路径)**:stub 的 `parse()` 返回 `extract_element_summary(normalized)`([stub.py:47](../src/syvern/adapters/stub.py)),故打通后 stub 模式下元素集与改造前逐字一致 → 现有断言(除签名外)结果不变。
- **真后端路径**:配置 `SYVERN_PILOT_ENDPOINT` 后,`self.pilot` 变为 `PilotAdapter`,`element_summary` 来自真 AST → 同一套下游代码自动消费真元素,**无需再改**。
- **抽象语法不变**:`ElementSummary(type, qualified_name)` 字段与归一化规则([models.py](../src/syvern/models.py))保持冻结;本改造只换"来源",不换"形状"。

---

## 8. 测试设计

| 类别 | 用例 | 期望 |
|---|---|---|
| 签名回归 | 全量 `pytest`(现 282) | 改签名后全绿 |
| 元素来源 | 注入一个 fake 适配器,其 `parse()` 返回与正则**不同**的元素集;断言结构/否决/规则/IPT 用的是适配器元素 | 用适配器元素,非正则 |
| 结构 | stub 模式 P/R/F1/coverage 与改造前一致 | 数值不变 |
| 否决 | 空/退化/枚举/占位仍按 stub 元素触发 | 行为不变 |
| IPT | 扰动经适配器解析;等价扰动→consistent,捷径→不一致 | 语义不变 |
| **红线回归(新增)** | 见 §8.1 | stub 下两者同分;接真后端后必翻转 |

### 8.1 红线回归用例(`tests/test_element_set_red_line.py`)
用一个"懂语法"的 fake 适配器(对损坏文本返回 `parse_ok=False` / 空元素)验证:

```python
def test_broken_model_scores_below_valid_with_real_parser():
    valid  = "part def Vehicle { attribute mass : Real; }"
    broken = "part def Vehicle { attribute mass : ; "   # 缺类型/缺括号
    pipe = ValidationPipeline(pilot_adapter=FakeSyntaxAwareAdapter())
    assert pipe.validate(valid).meta.reward  > pipe.validate(broken).meta.reward
```

意义:它把"合法 vs 损坏同得 0.900"这一缺陷钉成可执行断言。stub 阶段它依赖 fake 适配器演示通路已打通;接真 Pilot 后改用真适配器,该测试成为 H7 的验收门。

---

## 9. 实施步骤与提交拆分

| 序 | 提交 | 内容 | 可独立验证 |
|---|---|---|---|
| 1 | `refactor: thread parse element_summary into pipeline` | 加 `_elements` + `_finish(elements=...)`,结构匹配改用元素集 | ✅ |
| 2 | `refactor: pass elements into veto and rules` | 改 `evaluate_veto` / `evaluate_rules` 签名 + 调用方 + 移除 import | ✅ |
| 3 | `refactor: make IPT consume pre-parsed element sets` | 改 `evaluate_ipt`,pipeline 预解析扰动 | ✅ |
| 4 | `test: add element-source and red-line regressions` | §8 新增用例 | ✅ |

每步跑全量 `pytest` + `ruff` + `mypy`(CI 已就位,见 `.github/workflows/ci.yml`)。

---

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 改签名遗漏调用点 | mypy 严格类型 + 全量测试;`grep extract_element_summary` 确认仅剩 stub.py |
| IPT 扰动解析增加延迟 | 仅 `full` 模式触发,在线路径不跑;扰动数量有限 |
| stub 行为意外漂移 | §8 "结构/否决数值不变"回归用例兜底 |
| 与 H7 并行冲突 | 本改造先合入主干;H7 仅替换适配器实现,不碰下游签名 |

回滚:四个提交相互独立,可逐个 revert;接口变更集中、无数据迁移,回滚无副作用。

---

## 11. 验收标准

1. 全量测试通过;`extract_element_summary` 在 `src/syvern/` 内仅出现于 `stub.py`。
2. "元素来源"测试证明下游消费的是适配器元素而非正则。
3. 红线回归用例存在并通过(stub+fake 适配器)。
4. stub 模式下结构/否决/IPT 数值与改造前一致(无回归)。
5. 文档(本文件 + README 的实现状态段)同步更新:标注"元素集已打通,等接真后端"。

---

### 一句话总结
元素集打通 = 把"解析器产出的元素集"接成下游唯一来源,拆掉四处正则旁路。它纯仓内、可测、与 H7 解耦,**是让"接真 Pilot"真正产生效果的前置开关**;打通后,合法与损坏模型的奖励差异将随真后端的接入自动显现。
