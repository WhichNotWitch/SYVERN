# SYVERN 详细设计文档(LLD)

> **SYVERN** = *SysML V2 EValuation & Reward eNgine*
> 文档级别:详细设计(Low-Level Design)。承接《SYVERN 概要设计文档(HLD)》,达到可施工程度。
> 约定:下文 API 签名、字段、阈值为设计基线;落地时与真实工具输出/算力对齐。

---

## 1. 引言

本文档给出 SYVERN 各模块的内部逻辑、算法、数据结构、接口契约、配置项、错误处理与测试设计。模块划分与职责见 HLD §5。所有指标项标注其收敛层(T0/T1/T2)。

---

## 2. 模块详细设计

### 2.1 API 网关 & 调度

**接口**
```
POST /validate
Req:  { text: str, reference?: Model, mode: "online_reward"|"full"|"data_filter", k?: int }
Resp: 统一 JSON(§3)
```
**逻辑**
1. 计算 `text_hash = sha256(normalize_ws(text))`;`cache_key = (text_hash, validator_fingerprint, mode, ref_id)`。
2. 命中缓存 → 直接返回(幂等)。
3. 未命中 → 交编排器;返回前写缓存 + 落库。
**并发**:无状态 worker 池;后端调用(尤其 L0 JVM)用连接池/进程池复用,避免每次冷启动。
**幂等**:同 `cache_key` 必返回同结果;指纹变更使旧缓存失效。

### 2.2 后端适配器

#### 2.2.1 L0 Pilot 适配器(T0)
- **职责**:对 `text` 跑解析、名称解析、类型检查;把工具原生错误**归一化**为 `{stage, code, message, location}`。
- **接口(约定)**:`parse(text) -> AST|Errors`;`resolve(AST) -> {unresolved: [...]}`;`typecheck(AST) -> {type_errors: [...]}`。
- **指纹**:记录 Pilot 版本号、语法版本、规则集版本 → 写入 `meta.validator_fingerprint`。
- **错误归一化**:不同工具的错误文案映射到统一 `code` 枚举,便于跨版本比较与规则匹配。

#### 2.2.2 L0' MontiCore 适配器(T0,鲁棒性)
- 对同一 `text` 独立解析,产出 `parse_ok'`、结构摘要。
- **一致性判定**:`parser_agreement = (parse_ok == parse_ok') ∧ (元素集合摘要一致)`。元素摘要用规范化后的 `{type, qualified_name}` 多重集比较。
- 仅在 `full` 模式或周期校准时调用(开销大)。

#### 2.2.3 L1 规则引擎(T0)
- **规则注册表**:每条规则 `{id, derived_from_metamodel: bool, predicate(AST, ref?) -> bool, severity: error|warn}`。
- **元模型派生**:由 SysML v2 元模型约束自动生成 `predicate`(优先),减少手写。
- **抗作弊规则**驻留此层但单独标记 `category="anti_gaming"`,由抗作弊模块(§2.6)消费触发 Veto。
- **输出**:`constraint_violations = [{rule, severity}]`;`constraint_violations_weighted = Σ severity_weight`。

#### 2.2.4 L2 形式化适配器(T0+,离线/抽样)
- 适配 Imandra(SysML-v2→IML 后自动推理)、Gamma、nuXmv(符号模型检验)。
- **触发**:仅 `full` 模式抽样或里程碑评测;超时熔断。**结果不进在线奖励**,只入评测报告与监控。

### 2.3 Pipeline 编排器

**状态机**(逐级 gating):
```
S0 PARSE ──fail──▶ 记 t0_pass=false, S1..S5=未达到 ──▶ 汇总
   │ok
S1 RESOLVE ──fail──▶ 记后续未达到 ──▶ 汇总
   │ok
S2 TYPECHECK ─(记 type_errors,不阻断)─▶
   │
S3 CONSTRAINT ─(记 violations + 触发 Veto 判定)─▶ semantic_pass = S1∧S2 ok
   │
[mode==online_reward] ─▶ 汇总(跳过 S4/S5)
[mode==full] ─▶ S4 STRUCTURAL(需 reference)─▶ S5 INTENT(离线)─▶ 汇总
[mode==data_filter] ─▶ 应用门控阈值 ─▶ 通过/丢弃
```
**"未达到" vs "未评估"**:gating 失败标 `reached=false`;mode 未跑标 `evaluated=false`。二者在 JSON 中区分,避免把"没跑"误算为"没通过"。

### 2.4 指标计算器(公式)

记 `E_g`=生成模型元素集,`E_ref`=参照元素集(规约见 §2.5)。

**T0**
- `parse_ok ∈ {0,1}`
- `semantic_pass = parse_ok ∧ resolve_ok ∧ typecheck_ok`
- `pass@k`(按 prompt 聚合):k 次采样中存在 ≥1 次 `semantic_pass=1` → 1,否则 0
- `stable@k = (#{samples: semantic_pass=1}) / k`(鲁棒性)
- `unresolved_refs`, `type_errors`, `constraint_violations_weighted`:计数/加权计数

**T1(需 reference + 冻结策略)**
- `precision = |E_g ∩ E_ref| / |E_g|`(`|E_g|=0` 时定义为 0)
- `recall = |E_g ∩ E_ref| / |E_ref|`
- `f1 = 2·P·R / (P+R)`(P+R=0 时为 0)
- `requirement_coverage = |覆盖的参照需求| / |参照需求|`
- `ged_accuracy = 1 − GED(G_g, G_ref) / GED_max`(可选,`G`=元素+关系图)

**幻觉(T0/T1 交界)**
- `hallucinated_elements = |{ e ∈ E_g : e 引用未声明且无法由 spec 推出 }|`(分 `syntactic` / `semantic` 两类计数)

**归一化**(供奖励用,统一上限截断):
- `norm(x) = min(x / x_cap, 1)`,各计数项配独立 `x_cap`(配置项,§4)

**监控(不进奖励)**:`codebleu`, `levenshtein` 仅落库。

### 2.5 结构匹配器(T1)

**元素规约**:遍历 AST → 元素集 `{(type, qualified_name, attrs)}` + 关系边集 `{(src, kind, dst)}`。
**名称规范化(冻结策略 `matching_policy_id`)**:
1. 限定名拆解、大小写折叠、转义还原;
2. 去除自动生成后缀/编号;
3. 同义词典(可选,纳入策略指纹)。
**匹配算法**:
1. **确定性优先**:按 `(type, normalized_name)` 精确匹配 → 未命中按编辑距离 ≤ `fuzzy_threshold` 模糊匹配;
2. **语义对齐(T1-soft,降权)**:仍未匹配的叶节点,调 LLM 语义对齐裁判判定是否同义;结果标 `soft=true`,在奖励中降权。
**输出**:匹配对、`precision/recall/f1`、`requirement_coverage`、未匹配清单(供幻觉计数)。
**冻结约束**:`fuzzy_threshold`、归一化规则、同义词典一旦定版即写入指纹;变更视为新策略版本。

### 2.6 抗作弊模块(硬边界)

#### 2.6.1 Veto 规则
任一触发 → `veto.triggered=true, reason=...`,奖励置零:
- **空/退化**:`|E_g| < min_elements` 或 `token_count < min_tokens`,而 `semantic_pass=1`。
- **枚举式**:结构等价(仅字面量不同)的兄弟元素占比 > `enum_ratio`(应抽象却逐实例罗列)。
- **格式/显式作弊**:可疑重复填充、占位符堆叠、非标准格式骗过解析(规则层 `anti_gaming` 命中)。
- **解析器分歧**:`parser_agreement=false`。

**枚举检测启发式**:对兄弟元素做结构指纹(类型+关系拓扑,忽略字面量),指纹重复率 > `enum_ratio` 判定枚举。

#### 2.6.2 IPT 同构扰动测试
- **扰动生成器(双路)**:
  - 规则路:同义替换、语序重排、单位/量纲改写,保持语义等价;
  - LLM 路:改写 NL 规格,经回译/人工抽检确认等价。
- **一致性判定**:对扰动后的需求重新生成模型 `M'`,计算 `f1(struct(M'), struct(M_orig))`;若所有扰动下 `f1 ≥ ipt_threshold` → `ipt_consistent=1`,否则 0(疑似捷径/作弊)。
- **用途**:周期性鲁棒性评测;可作奖励正向项 `w6`(可选)。

### 2.7 意图裁判(T2)

- **裁判模型**:选低偏置模型;对裁判**屏蔽生成模型身份**。
- **rubric**(0–5 维度):覆盖度、正确性、过/欠拟合;给正反例(G-Eval 风格);版本号入指纹。
- **流程(保持简单,非 agentic)**:
  1. pointwise 打分;或 pairwise 比较时**交换顺序两次取平均**(消位置偏置);
  2. N 次投票/集成取中位或多数;
  3. 跨模型评审消自偏好偏置。
- **校准闭环**:抽样人工复核 → 算 Cohen κ;`κ < κ_min` → 修 rubric 重测。
- **边界**:`intent_score` 写入 `intent.score`,**仅入监控与 RLHF/DPO 偏好**,绝不进奖励映射。

### 2.8 奖励映射器

```python
def reward(j, cfg):                       # j = 统一 JSON, cfg = 权重/上限配置
    if j["veto"]["triggered"]:
        return 0.0                        # 硬边界
    s = j["stage"]
    st = j["structural"]
    r  = cfg.w0 * (1 if s["parse"]["ok"] and s["parse"]["parser_agreement"] else 0)
    r += cfg.w1 * (1 if s["resolve"]["ok"] else 0)
    r += cfg.w2 * (1 - norm(s["typecheck"]["type_errors"], cfg.cap_type))
    r += cfg.w3 * (1 - norm(weighted(s["constraint"]["violations"]), cfg.cap_cons))
    r += cfg.w4 * st["f1"]                                   # T1, 降权
    r += cfg.w5 * st["requirement_coverage"]                 # T1, 防空模型
    r += cfg.w6 * (1 if j["robustness"]["ipt_consistent"] else 0)   # 可选抗作弊正向项
    r -= cfg.w7 * norm(st["hallucinated_elements"], cfg.cap_hall)
    return clip(r, 0.0, cfg.r_max)
    # 注:intent.score 不参与本式
```
**要点**:T0(w0–w3)为主、阶梯式;T1 覆盖项(w4–w5)必留但降权;Veto 先于一切;意图层不入。

### 2.9 RL 有效区间监控

- **散点**:对一批样本绘 `semantic_pass × requirement_coverage`。
- **发散检测**:滑窗内 `semantic_pass` 升而 `requirement_coverage` 不升(或 Veto 触发率上升)→ 报"进入作弊区"告警。
- **鲁棒性**:跟踪 `stable@k` 趋势,骤降视为信号在噪声中漂移。

---

## 3. 统一输出 Schema(逐字段)

```jsonc
{
  "sample_id": "str",
  "tier_summary": { "t0_pass": "bool", "t1_available": "bool", "veto": "bool" },
  "stage": {
    "parse":      { "reached": "bool", "ok": "bool", "parser_agreement": "bool", "errors": "Error[]" },
    "resolve":    { "reached": "bool", "ok": "bool", "unresolved_refs": "int>=0", "errors": "Error[]" },
    "typecheck":  { "reached": "bool", "ok": "bool", "type_errors": "int>=0", "errors": "Error[]" },
    "constraint": { "reached": "bool", "ok": "bool", "violations": "Violation[]" }
  },
  "structural": {
    "evaluated": "bool",
    "precision": "float[0,1]", "recall": "float[0,1]", "f1": "float[0,1]",
    "requirement_coverage": "float[0,1]", "ged_accuracy": "float[0,1]|null",
    "hallucinated_elements": "int>=0",
    "matching_policy_id": "str"
  },
  "robustness": { "stable_at_k": "float[0,1]|null", "ipt_consistent": "bool|null" },
  "intent": { "evaluated": "bool", "score": "float|null", "source": "llm_judge|human|null" },
  "veto": { "triggered": "bool", "reason": "str|null" },
  "monitor": { "codebleu": "float|null", "levenshtein": "int|null" },
  "meta": { "latency_ms": "int", "mode": "str", "validator_fingerprint": "str" }
}
// Error = {stage, code, message, location}; Violation = {rule, severity}
```

---

## 4. 配置项规格

| 配置 | 含义 | 基线/范围 |
|---|---|---|
| `w0..w7` | 奖励权重 | RL 阶段调;字段口径冻结 |
| `cap_type/cap_cons/cap_hall` | 归一化上限 | 按数据分布定 |
| `r_max` | 奖励上限 | 1.0 |
| `min_elements/min_tokens` | 退化阈值 | 经验起点,需调 |
| `enum_ratio` | 枚举判定阈值 | 0.6~0.8 起 |
| `fuzzy_threshold` | 结构模糊匹配阈值 | 入策略指纹 |
| `ipt_threshold` | 扰动一致性 F1 阈值 | 0.8 起 |
| `k` | 采样次数 | pass@k/stable@k 用 |
| `kappa_min` | 裁判校准下限 | 0.6 起 |
| `validator_fingerprint` | 后端版本指纹 | 自动生成 |
| `matching_policy_id` | 匹配策略版本 | 冻结 |
| `judge_model/rubric_version` | 裁判配置 | 入指纹 |

---

## 5. 错误处理与边界条件

- **空输入 / 超长输入**:网关侧拦截;超长按截断策略并标记。
- **后端超时 / 崩溃**:熔断,返回 `reached=false` 并记错误码;L2 超时不影响 L0+L1 结果。
- **无 reference 却请求 full**:Stage 4 标 `evaluated=false`,不报错。
- **`|E_g|=0`**:precision/f1=0;触发退化 Veto 判定。
- **裁判不返回结构化分**:重试 N 次后置 `score=null, evaluated=false`,不阻断。
- **指纹缺失**:拒绝写缓存,强制重算。

---

## 6. 并发、缓存与幂等

- 后端进程/连接池复用,避免 JVM 冷启动;批量请求合并调度。
- 缓存键含指纹与 mode;LRU + 指纹失效。
- 幂等保证:同键同结果;非确定项(语义对齐 soft、裁判)在 `online_reward` 模式默认关闭,确保奖励路径纯确定性。

---

## 7. 测试设计

| 类别 | 用例 |
|---|---|
| 确定性 | 同输入多次调用结果完全一致;指纹变更触发重算 |
| 分层正确性 | 构造仅语法错 / 仅类型错 / 仅未解析引用的样本,验证 stage 判决与 gating |
| 结构匹配 | 同义异名、字面量差异、缺失/多余元素的 P/R/F1 正确性;策略冻结回归 |
| 抗作弊 | 空模型 / 枚举式 / 占位填充 / 解析器分歧 → 必触发 Veto 置零 |
| IPT | 等价扰动下结构等价输出 → consistent;捷径输出 → 不一致 |
| 裁判校准 | 位置交换不改结论;与人工 κ 达标;屏蔽身份生效 |
| 奖励映射 | Veto→0;T0 阶梯单调;意图分变化不影响奖励 |
| 性能 | online_reward 单条延迟与批量吞吐达标 |

---

## 8. 与里程碑对应

| LLD 模块 | 对应里程碑(HLD §—) |
|---|---|
| §2.2.1/2.2.3 + §2.3 + §2.4(T0) + §3 + §6 | H1 T0 核心 |
| §2.2.2 + §2.4(stable@k) | H2 交叉与鲁棒 |
| §2.5 | H3 结构层 |
| §2.6 | H4 抗作弊 |
| §2.7 | H5 意图与校准 |
| §2.8 + §2.9 | H6 奖励就绪 |
