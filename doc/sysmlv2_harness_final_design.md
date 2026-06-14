# SYVERN · SysML v2 生成校验与奖励引擎 — 最终设计方案

> **SYVERN** = *SysML V2 EValuation & Reward eNgine*
> *SysML v2 生成的守门人:分层校验,评测即奖励,作弊过不了关。*

> 定位:SYVERN 是「评测器 = 奖励器」的统一服务,贯穿 SFT 数据过滤、训练评测、RFT 筛选、RLVR 奖励四个用途。本文档为施工级规范,与《SFT 阶段执行文档》(数据构造)互为配套。
> 版本基准:SysML v2.0 / KerML 1.0 / Systems Modeling API & Services 1.0(2025 正式规范),Pilot Implementation 参考实现。

---

## 1. 设计原则

1. **一次搭建,两阶段复用**:同一套校验逻辑产出同一份 JSON,既是评测指标也是奖励函数的输入。SFT 阶段定字段与口径,RL 阶段只调权重。
2. **收敛范围分层**(本方案的骨架,见 §2):只有"确定性核心"进确定性奖励;条件收敛项降权;不收敛项仅作监控/偏好。
3. **服务化、无状态、可缓存、幂等**:RL 在线每步要校验上百条采样,单条校验必须高吞吐、同输入同输出、结果可缓存。
4. **版本钉死可复现**:验证器后端版本写入 SYVERN 指纹,纳入每条结果的 `meta`,保证跨时间结果可比。
5. **抗作弊优先于召回**:宁可漏报(规则没覆盖)也不能给作弊输出高奖励;否决层是硬边界。

---

## 2. 收敛范围边界规范(核心约束)

SYVERN 的每个信号按"是否收敛"分三层(T0/T1/T2),决定它能否进奖励、以什么权重进。判定依据四性质:**确定性**(同输入同输出)、**有界性**、**参照无关性**、**梯度有意义**。

| 层 | 信号 | 确定 | 有界 | 参照无关 | 用途 |
|---|---|---|---|---|---|
| **T0 完全收敛核心** | 解析 / 名称解析 / 类型检查 / 元模型规则违反 | ✓ | ✓ | ✓ | 确定性奖励主信号 |
| **T1 条件收敛** | 结构 F1 / GED / 需求覆盖率 | ✓* | ✓ | ✗(依赖参照+匹配策略) | 降权辅助奖励 |
| **T2 不收敛** | 意图保真(LLM-judge) | ✗ | ✓ | ✗ | 仅监控 / RLHF 偏好,**禁入 RLVR** |

\* T1 仅在「固定参照 + 冻结匹配策略」下确定;开放式需求存在多个等价正确模型,故 T1 只收敛到"与选定参照的距离",非唯一目标。

**两条必须写进设计的边界事实:**

- **收敛 ≠ 正确(完整性天花板)**:即使 T0 全过,也只证明良构性 + 名称/类型一致性 + 已实现规则,**不证明系统建对了**。"通过验证器但建错系统"的假阳性区在 SYVERN 视野之外;规则层写多全,边界就外推多远,但永远到不了"真实正确"。
- **RL 有效区间**:verifier-reward 只在"与真实质量同向"区间内有效。策略一旦刷满 T0、开始钻 T0 与真实正确之间的缝(reward hacking),指标饱和但真实质量不再跟涨。必须在线监控这条发散点(见 §7.3)。

---

## 3. 后端架构

采用**多源后端 + 规则层**,按成本/确定性分级调用:

```
                ┌─────────────────────────────────────────────┐
   model text → │  L0  Pilot Implementation (Xtext, 权威, 慢)   │ ← 主判决
                │  L0' MontiCore parser (独立第二解析器)        │ ← 交叉一致性
                │  L1  元模型派生规则层 (轻量, 快, 可扩展)       │ ← T0 语义约束 + 抗作弊
                │  L2  形式化工具 Imandra/Gamma (可选, 抽样)    │ ← 深度语义, 离线
                └─────────────────────────────────────────────┘
                                  ↓ 统一 JSON (§8)
```

- **L0 / L0' 双解析器交叉**:两个独立实现(官方 Pilot + MontiCore)对同一文本的解析/校验结论是否一致,作为稳健性信号,抓单解析器漏报。不一致 → 标记 `parser_disagreement`,该样本不进奖励(或降权)。
- **L1 元模型派生规则层**:从 SysML v2 元模型导出校验规则(metamodel-driven validation),而非手写。这是你可控、可扩展的部分,也是把 T0 边界外推的主要手段。抗作弊规则(空模型/枚举式)也放这层。
- **L2 形式化工具(可选)**:Imandra(SysML-v2→IML 转译后自动推理)、Gamma、nuXmv(符号模型检验,可作 Gamma 等框架的后端引擎)等,用于深度语义/契约检查。慢,只对里程碑评测或抽样跑,**不进在线奖励**。
- **工程约束**:在线奖励用 L0+L1(钉版本、缓存);L0' 交叉与 L2 形式化周期性校准。单条结果按文本哈希缓存,幂等。

> ⚠️ 各工具确切 API 以实际拉取版本为准;本文 JSON 字段为约定接口,落地时与真实输出对齐。Pilot Implementation 的校验约束随版本变化(部分约束从自动满足改为需显式满足),务必钉版本。

---

## 4. 分层校验 Pipeline(逐级 gating)

```
Stage 0  PARSE       词法/语法解析成功?            [T0]
Stage 1  RESOLVE     所有引用指向已声明元素?       [T0]
Stage 2  TYPECHECK   类型检查 / KerML 语义约束?    [T0]
Stage 3  CONSTRAINT  元模型派生规则 + 抗作弊检查     [T0 规则 / 否决层]
─────────────────── 以上为确定性核心,以下需参照 ───────────────────
Stage 4  STRUCTURAL  与参照模型的结构匹配           [T1]
Stage 5  INTENT      LLM-judge 意图保真             [T2, 仅监控/偏好]
```

任一 Stage 失败,后续 Stage 标记为"未达到"(区别于"未评估");逐级 gating 天然形成阶梯式 reward shaping,缓解稀疏奖励。Stage 0–3 不依赖参照,可对任意生成样本运行;Stage 4 需参照模型;Stage 5 仅离线/监控。

---

## 5. 指标定义

**T0 句法层**
- `parse_ok`(bool):Stage 0
- `parser_agreement`(bool):L0 与 L0' 结论一致
- `pass@k`:k 次采样中 ≥1 次「解析成功且通过 Stage 1–2」
- `stable@k`:k 次中通过 Stage 1–2 的比例(鲁棒性,应对 LLM 随机性,对应 NSVP 思路)

**T0 语义层**
- `resolve_ok` / `unresolved_refs`(未解析引用数)
- `typecheck_ok` / `type_errors`(类型错误数)
- `constraint_violations`:规则违反数,按严重度加权
- `semantic_pass`(bool):Stage 1–2 全过

**T1 结构相似层(需参照 + 冻结匹配策略)**
- 元素级 `precision / recall / f1`:生成模型与参照模型都规约为元素集合(part/attribute/connection/requirement/...),按「类型 + 规范化名称」匹配
- `requirement_coverage`:参照需求被覆盖比例
- `ged_accuracy`(可选):图编辑距离准确率,衡量拓扑依赖一致性

**幻觉指标(T0/T1 交界)**
- `hallucinated_elements`:引用了规格中不存在、且无法从上下文推出的元素/关系数(分句法幻觉 / 语义幻觉)

**T2 意图层(仅监控/偏好)**
- `intent_score`:LLM-judge 评分(见 §6),不进 RLVR

**辅助监控(不进奖励)**
- `codebleu` / `levenshtein`:仅作监控。**禁入主指标与奖励**——句法相似度会双向误导(合法异构写法被判低、含语义错误的相似代码被判高)。

---

## 6. 结构匹配与意图裁判

### 6.1 结构匹配(Stage 4,T1)
- **元素规约**:把模型抽象为带类型的元素集合 + 关系边集合。
- **匹配策略冻结**:名称规范化规则(大小写/限定名/转义)、模糊阈值一旦定下即冻结并写入 SYVERN 指纹——否则 T1 指标不可复现。
- **确定性优先**:先用规范化精确/模糊匹配;仅在剩余未匹配叶节点上,才调用 LLM 语义对齐裁判解决"同义异名"。注意此步引入随机性,结果标记为 T1-soft,降权。

### 6.2 意图裁判(Stage 5,T2)
- **保持简单**:单模型 + 固定 rubric + 多次投票。裁判打分一致性与流程复杂度成反比,**不做 agentic 多步框架**。
- **rubric**:覆盖度 / 正确性 / 过拟合-欠拟合,0–5 分维度,给正反例(G-Eval 风格)。
- **去偏**:对裁判屏蔽生成模型身份;pairwise 时交换顺序取平均(消位置偏置);跨模型/集成评审消自偏好偏置;控制 verbosity。
- **校准**:抽样人工复核,算与人工的一致性(Cohen κ),低于阈值则修 rubric。当作持续校准的生产组件,不是一次性 prompt。
- **边界**:`intent_score` 永不进 RLVR 确定性奖励;只用于监控仪表盘与 RLHF/DPO 偏好数据。

---

## 7. 鲁棒性与抗作弊(硬约束)

### 7.1 否决层(veto,奖励硬边界)
以下任一触发 → **奖励置零**(而非扣分),并记 `veto_reason`:
- **空/退化模型**:元素数或 token 数低于阈值却"校验通过"。
- **枚举式作弊**:本应抽象建模却逐实例罗列(外延式而非内涵式),对应"放弃规则归纳、枚举实例标签"的 reward hacking。
- **格式/显式作弊**:非标准格式骗过解析、可疑的重复/占位填充。
- **解析器分歧**:`parser_agreement = false`。

### 7.2 同构扰动测试(IPT)
对需求做**逻辑等价改写/扰动**,要求模型输出**结构等价**的正确模型。只在外延上通过、扰动后失败 → 判定为捷径/作弊。这是 SysML 版的"防枚举",把覆盖项变得抗作弊。建议作为周期性鲁棒性评测,并可将"扰动一致性"作为一个额外奖励项。

### 7.3 RL 有效区间监控
在线看 **`semantic_pass` × `requirement_coverage` 散点**:
- 健康:同时往右上(合法且覆盖)。
- 发散预警:只往右不往上(合法但空/作弊)→ 已越出 RL 有效区间,verifier-reward 失效,需扩验证器(加 §3-L1 规则)或切偏好/人工信号。
- 配合 `stable@k`(多次运行稳定通过率)确认信号未在噪声中漂移。

---

## 8. 标准输出 Schema(评测 = 奖励输入)

```json
{
  "sample_id": "str",
  "tier_summary": {"t0_pass": true, "t1_available": true, "veto": false},
  "stage": {
    "parse":      {"ok": true,  "parser_agreement": true, "errors": []},
    "resolve":    {"ok": true,  "unresolved_refs": 0, "errors": []},
    "typecheck":  {"ok": false, "type_errors": 2, "errors": ["..."]},
    "constraint": {"ok": false, "violations": [{"rule": "...", "severity": "error"}]}
  },
  "structural": {
    "precision": 0.0, "recall": 0.0, "f1": 0.0,
    "requirement_coverage": 0.0, "ged_accuracy": null,
    "hallucinated_elements": 0,
    "matching_policy_id": "frozen-v1"
  },
  "robustness": {"stable_at_k": 0.0, "ipt_consistent": null},
  "intent": {"score": null, "source": "llm_judge|human|null"},
  "veto": {"triggered": false, "reason": null},
  "monitor": {"codebleu": null, "levenshtein": null},
  "meta": {"latency_ms": 0, "validator_fingerprint": "pilot@x.y+monti@z+rules@v1"}
}
```

---

## 9. 奖励函数映射(RLVR 阶段)

字段在 SFT 阶段冻结,权重在 RL 阶段调。

```
if veto.triggered:        r = 0                      # 硬边界
else:
  r =  w0 * 1[parse_ok ∧ parser_agreement]           # T0 阶梯
     + w1 * 1[resolve_ok]
     + w2 * (1 - norm(type_errors))
     + w3 * (1 - norm(constraint_violations_weighted))
     + w4 * f1_structural          # T1, 降权
     + w5 * requirement_coverage   # T1, 防"合法但空"
     + w6 * 1[ipt_consistent]      # 抗作弊正向项(可选)
     - w7 * norm(hallucinated_elements)
  # intent_score 不进此式;仅入 RLHF/DPO 偏好或监控
```

要点:T0 项(w0–w3)为主、阶梯式;T1 覆盖项(w4–w5)必留以防空模型作弊但降权;否决层先于一切;意图层不入。

---

## 10. 接口与工程

- **服务接口**:`POST /validate {text, reference?, mode}` → §8 JSON;`mode ∈ {full, online_reward, data_filter}` 控制跑到哪个 Stage、是否调 L0'/L2。
- **吞吐**:`online_reward` 模式只跑 L0+L1,目标单条 < 数百 ms、可批量并发;`full` 模式可含 L0'/L2/IPT。
- **缓存**:按 `(text_hash, validator_fingerprint)` 缓存,幂等。
- **可观测**:落库每条结果,支持按 tier / domain / difficulty / checkpoint 分层对比(SFT vs RFT vs RLVR)。

---

## 11. 里程碑与验收

| 里程碑 | 交付 | 验收口径 |
|---|---|---|
| H1 T0 核心 | L0+L1 服务 + §8 JSON + 版本指纹 | Stage 0–3 可批量/在线,同输入同输出,版本可复现 |
| H2 交叉与鲁棒 | L0' 交叉一致性 + `stable@k` | 解析分歧可检出;多次运行稳定指标可用 |
| H3 结构层 | Stage 4 + 冻结匹配策略 | T1 指标在固定参照下可复现;同义异名经语义对齐 |
| H4 抗作弊 | 否决层 + IPT | 空/枚举/格式作弊被置零;扰动一致性可评 |
| H5 意图与校准 | Stage 5 LLM-judge + κ 校准 | 与人工一致性达标;确认未进 RLVR 奖励 |
| H6 奖励就绪 | §9 奖励函数接 SYVERN | 在线吞吐达标;权重项齐备;§7.3 发散监控在线 |

---

## 附:关键参考(供团队追溯)

- SysML v2 Pilot Implementation(Systems-Modeling);MontiCore SysML v2 parser
- Towards the Formal Verification of SysML v2 Models(MODELS Companion '24);Ensuring Semantic Consistency in SysML v2 Models through Metamodel-Driven Validation(IEEE Access)
- SysTemp: A Multi-Agent System for Template-Based Generation of SysML v2
- Generating SysML Behavior Models via LLMs: an Empirical Study(Internetware '24)
- LLM-enabled Instance Model Generation;R2ABench(Requirement-to-Architecture, hybrid eval)
- LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking(IPT);Reward Hacking in RLVR(综述)
- EnvTrace(语义优于句法评测);DevBench;AXIOM / Bias-in-the-Loop(LLM-as-judge 校准)

---

### 一句话总结
SYVERN 的可信边界由收敛分层定义:**T0 确定性核心是奖励的根**,T1 结构覆盖降权辅助、防空模型,T2 意图层只监控不入奖励;否决层与 IPT 是抗作弊硬边界,RL 有效区间靠 coverage×pass 散点在线监控。把这条边界守住,SFT 阶段产出的就是一套到 RLVR 可直接复用、且不会被钻空子的评测/奖励基础设施。
