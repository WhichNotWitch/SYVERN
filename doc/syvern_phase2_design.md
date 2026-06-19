# SYVERN 实现对齐与生产化设计文档

> **SYVERN** = *SysML V2 EValuation & Reward eNgine*
> 文档级别:阶段二设计(后端落地 + 算法补全 + 生产化)。承接 HLD / LLD 与 H1–H6 已交付骨架。
> 目标读者:继续开发 SYVERN 的工程团队。
> 约定:文中引用的符号(如 `PilotStubAdapter`、`match_structural`、`SyvernSettings`)均指现有仓库代码;接口签名为设计基线,以真实工具输出对齐。

---

## 1. 背景:当前已交付的是"控制平面",不是"验证实体"

H1–H6 已交付一个忠实于 LLD 的骨架:统一 Schema、分层 gating、reward shaping、否决门、tier 逻辑、监控聚合、缓存/记录/API,140 项测试通过。但所有真正做"判断"的后端均为 stub 或确定性占位逻辑。本设计文档定义把骨架变为可用验证器/奖励器所需的全部工作。

### 1.1 缺口清单(本设计要闭合的对象)

| 编号 | 缺口 | 现状 | 收敛层 | 优先级 |
|---|---|---|---|---|
| G1 | T0 解析后端为 stub | `PilotStubAdapter` 靠魔法字符串触发,元素抽取靠正则 | T0 | P0 |
| G2 | L0' 交叉仅 full 模式跑;在线奖励路径 `parser_agreement` 恒 True | `pipeline.validate` | T0 | P0 |
| G3 | 结构匹配只有精确匹配 | `match_structural` 为 Counter 交集 | T1 | P1 |
| G4 | IPT 偏离定义,且无扰动生成器 | `evaluate_ipt` 对参照算 F1 | 抗作弊 | P1 |
| G5 | 意图裁判非 LLM,投票退化 | `evaluate_intent` 确定性短语匹配 | T2 | P1 |
| G6 | L2 形式化适配器缺失 | 无 | T0+ | P2 |
| G7 | `stable_at_k` 语义错位 | 监控里等于 pass 率 | 监控 | P1 |
| G8 | 缓存/并发/`data_filter`/CI 等生产化缺口 | 进程内裸 dict 等 | 工程 | P2 |

### 1.2 设计原则(延续)
确定性核心(T0)优先落地;每个真实后端都要配"对齐测试集";`intent` 永不进奖励;改变判决的任何东西(后端版本、匹配策略、rubric)都要进指纹并触发缓存失效。**收敛 ≠ 正确**:接真后端只是把空跑变成有效,不等于模型正确,语义鸿沟仍需后续规则层与 L2 外推。

---

## 2. G1 · 真实 L0 Pilot 适配器(P0)

### 2.1 接口(替换 `PilotStubAdapter`,保持 `ValidatorAdapter` 协议)
保持 `adapters/base.py` 的 `parse/resolve/typecheck` 三方法签名不变,新增 `PilotAdapter` 实现:

```python
class PilotAdapter:  # adapters/pilot.py
    name = "pilot"
    def __init__(self, endpoint: str, version: str, timeout_s: float): ...
    def parse(self, text: str) -> ParseResult: ...      # AST + 真元素集 + 归一化错误
    def resolve(self, text: str) -> ResolveResult: ...   # 名称解析
    def typecheck(self, text: str) -> TypecheckResult: ...
    def fingerprint(self) -> str: ...                    # 工具版本/语法版本/规则集
```

### 2.2 后端进程模型
Pilot Implementation 为 JVM/Xtext。两种接入:(a)常驻服务进程 + IPC/HTTP;(b)Systems Modeling API & Services。**禁止每条冷启动 JVM**——必须连接池/常驻。在线奖励路径对延迟敏感,这是硬约束。

### 2.3 AST → ElementSummary 映射
用真实 AST 替换 `stub.ELEMENT_PATTERN` 正则。映射规则:遍历 AST,产出 `ElementSummary(type, qualified_name)`,`type` 取 KerML/SysML 元类型(part/attribute/connection/requirement/action/item/...),`qualified_name` 取完全限定名。该映射是 T1 结构匹配的输入,必须稳定、确定。

### 2.4 错误归一化
不同工具错误文案映射到统一 `ErrorDetail.code` 枚举(如 `RESOLVE_UNRESOLVED_REF`、`TYPECHECK_*`),便于跨版本比较与规则匹配。建立 `code` 枚举注册表。

### 2.5 对齐测试集(验收前提)
构造 ≥ 50 条人工标注 `.sysml`,每条标注期望的 `parse_ok / unresolved_refs / type_errors`,覆盖:纯语法错、未解析引用、类型错、合法模型、嵌套/规模梯度。适配器对齐测试 = 适配器输出与标注一致率达标。

### 2.6 指纹
`validator_fingerprint` 写入 Pilot 真实版本号(替换当前 `*-stub@0.6.0`)。指纹变更 → 缓存失效(见 §9)。

---

## 3. G2 · L0' MontiCore 交叉与在线路径修正(P0)

### 3.1 何时跑
- `full` / 校准路径:跑 `MontiCoreAdapter.parse`,产出 `parser_agreement`。
- `online_reward` 路径:默认不跑(吞吐),但**修正 reward 语义**:当 L0' 未运行时,`parser_agreement` 应为"未知"而非 `True`,且 reward 的 w0 项不得依赖一个未实际检验的量。

### 3.2 修正方案(择一,推荐 A)
- **A(推荐)**:reward 的 w0 仅 gate 在 `parse.ok`;`parser_agreement` 仅作为否决层信号(为 False 才置零),在线模式下取 `None`→不否决。这样在线奖励不再依赖未运行的交叉检查,而 full/抽样路径仍能用分歧触发否决。
- **B**:在线路径也跑 MontiCore(吞吐换稳健),仅当 SLA 允许。

### 3.3 一致性判定(保留现有)
`parser_agrees` 用规范化 `(type, qualified_name)` 多重集比较,已实现,接真 AST 后自然生效。

---

## 4. G3 · 结构匹配补全(P1)

现状 `match_structural` 为精确交集,召回偏低(同义异名→误判幻觉)。按 LLD §2.5 补三段式。

### 4.1 规范化层(扩展 `ElementSummary` 之外的策略)
在精确键之上增加策略化规范化:限定名拆分、自动生成后缀/编号去除、可选同义词典。规范化规则集合冻结为新的 `matching_policy_id`(从 `h3-frozen-exact-v1` 升级,写入指纹)。

### 4.2 模糊匹配
未精确命中的元素,按同类型内 `normalized_name` 编辑距离 ≤ `fuzzy_threshold` 匹配(新增 settings 项)。模糊匹配计入 precision/recall,但标记来源以便审计。

### 4.3 T1-soft 语义对齐
仍未匹配的叶节点,调 LLM 语义对齐裁判判同义;命中标 `soft=true`,在奖励中**降权**(不与确定性匹配同权)。Schema 增 `structural.soft_matched` 计数,reward 对 soft 部分单独系数。

### 4.4 影响
补全后 `hallucinated_elements` 不再把同义异名误计为幻觉;F1/覆盖率更贴近真实。策略升级后需重跑结构层回归基线。

---

## 5. G4 · IPT 重构(P1)

现状 `evaluate_ipt` 把 `perturbations` 当成模型文本逐个对参照算 F1,**不是同构测试**。按 LLD §2.6.2 重构。

### 5.1 正确语义
对原始需求生成 `M_orig`;对每个等价扰动需求**重新生成** `M'`;计算 `f1(struct(M'), struct(M_orig))`;若所有扰动 `f1 ≥ ipt_threshold` → `ipt_consistent = True`,否则 False。即比较"原始输出 vs 扰动输出",而非"扰动 vs 参照"。

### 5.2 扰动生成器(双路,新增 `ipt_perturb.py`)
- **规则路(先行)**:同义替换、语序重排、单位/量纲改写,保证语义等价。
- **LLM 路**:改写 NL 规格,经回译/人工抽检确认等价。
- 接口:`generate_perturbations(spec: str, n: int) -> list[str]`。

### 5.3 接口调整
当前 `evaluate_ipt(perturbations, reference, settings)` 改为需要"生成函数 + 原始输出",或在调用方先生成 `M'` 集合再传入比较。明确区分"扰动需求"与"扰动输出"。

### 5.4 奖励
`ipt_consistent` 作为可选正向项 `w6`(现 0.0),抗作弊用;默认仍 0,RL 阶段再开。

---

## 6. G5 · 真 LLM 意图裁判(P1)

现状 `evaluate_intent` 是确定性短语匹配,却标 `source="llm_judge"`,且 N 票相同。按 LLD §2.7 替换。

### 6.1 真裁判
- 单模型 + 固定 rubric(覆盖度/正确性/过-欠拟合,0–5),给正反例;对裁判屏蔽生成模型身份。
- pairwise 场景交换顺序两次取平均(消位置偏置);多模型/集成消自偏好。
- `intent_vote_count` 改为对"有随机性的裁判"多次采样取中位/多数;确定性占位下投票无意义,需随真裁判一起改。

### 6.2 校准(复用现有 `calibration.py`)
现有 Cohen κ 与 `kappa_min` 验收闭环保留;接真裁判后用人工标注集算 κ,低于阈值改 rubric 重测。

### 6.3 标注修正
未接真裁判前,`source` 不得标 `llm_judge`(误导);可临时标 `heuristic` 或保持 `evaluated=False`。

### 6.4 边界(不变)
`intent.score` 永不进 reward(现已正确),仅入监控与 RLHF/DPO 偏好。

---

## 7. G6 · L2 形式化适配器(P2)

新增 `adapters/formal.py`,适配 Imandra(SysML-v2→IML 自动推理)、Gamma、nuXmv(符号模型检验,可作 Gamma 后端)。

- **触发**:仅 `full` 抽样或里程碑评测;**不进在线奖励**。
- **熔断**:超时即放弃,不影响 L0+L1 结果。
- **产出**:深度语义/契约结论入评测报告与监控,不入 reward 标量。

---

## 8. G7 · 监控修正(P1)

`aggregate_monitor_summary` 中 `stable_at_k` 现等于 `semantic_pass_rate`,语义错位。修正:

- stable@k 必须**按 prompt 分组**:同一 prompt 的 k 次采样里通过 Stage 1–2 的比例,再对 prompt 取平均。需要记录里带 prompt 分组键(扩展 `ValidationRecord` 增 `prompt_id`)。
- 保留 `semantic_without_coverage` / `veto_rate_increase` / `stable_at_k_drop` 三类发散告警;后者依赖修正后的 stable@k。

---

## 9. G8 · 生产化(P2,RLVR 在线奖励前置)

| 项 | 现状 | 目标 |
|---|---|---|
| 缓存 | 进程内裸 dict,无淘汰/失效/锁 | LRU + 指纹失效 + 线程/进程安全 |
| 后端 | 无连接池 | Pilot/MontiCore 常驻 + 池化,避免 JVM 冷启动 |
| `data_filter` 模式 | 声明未实现 | 跑到 Stage 3 + 阈值门控(通过/丢弃) |
| 幂等 | 在线路径含非确定项风险 | 在线模式关闭 soft 对齐/随机裁判,保证奖励路径纯确定 |
| CI | 无 | pytest + 类型检查 + lint + 确定性回归 |
| 基准 | 无 | `online_reward` 单条延迟 + 批量吞吐基准 |

---

## 10. 一致性测试与验收

| 类别 | 用例 |
|---|---|
| 适配器对齐 | Pilot/MontiCore 输出与人工标注集一致率达标(§2.5) |
| 确定性回归 | 同输入多次调用结果完全一致;指纹变更触发重算 |
| 结构策略冻结 | 策略升级前后基线对比;`matching_policy_id` 入指纹 |
| IPT | 等价扰动→输出同构→consistent;捷径输出→不一致 |
| 裁判校准 | 交换顺序不改结论;与人工 κ ≥ `kappa_min`;屏蔽身份生效 |
| 奖励隔离 | `intent.score` 变化不影响 reward;Veto→0;T0 阶梯单调 |
| 吞吐 | online_reward 延迟/吞吐达 SLA |

---

## 11. 里程碑与依赖顺序

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| H7 | G1 真 Pilot 适配器 + 对齐测试集 | — |
| H8 | G2 L0' 交叉修正 + 在线 reward 语义修正 | H7 |
| H9 | G3 结构匹配补全(规范化/模糊/T1-soft) | H7 |
| H10 | G4 IPT 重构 + 扰动生成器 | H9 |
| H11 | G5 真 LLM 裁判 + κ 校准 | — |
| H12 | G7 监控修正 + G8 生产化 + G6 L2(抽样) | H7–H11 |

关键路径:**H7 是一切的前提**(没有真 T0,后续指标都空跑)。H9 在 H7 之后才有真元素集可匹配。H11(裁判)可与 T0 线并行。

---

## 12. 风险

| 风险 | 缓解 |
|---|---|
| Pilot JVM 延迟拖垮在线奖励 | 常驻 + 池化;在线只 L0+L1;L2/MontiCore 抽样 |
| 真后端引入非确定性(版本/环境) | 钉版本 + 指纹 + 确定性回归;在线关随机项 |
| 结构策略升级使历史指标不可比 | 策略版本化入指纹;升级即重建基线 |
| 接真后端后空跑指标被误信 | STATUS.md 标注 stub/real;**收敛 ≠ 正确**写入文档与评审 |
| 裁判偏置渗入偏好数据 | 简单 rubric + 交换平均 + 跨模型 + κ 持续校准 |

---

### 一句话总结
骨架(控制平面)已成,本阶段把每个 stub 换成真实体:**H7 接真 Pilot 是解锁一切的前提**,随后补全结构匹配、重构 IPT、换上真 LLM 裁判、修正监控、完成生产化。守住三条不变量——确定性核心优先、`intent` 不入奖励、改判决者必入指纹——SYVERN 才能从"能跑通"变成"可挂上 RLVR 训练"。
