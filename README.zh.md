# SYVERN

**SYVERN** = *SysML V2 EValuation & Reward eNgine*(SysML v2 评测与奖励引擎)

> [English](README.md) · **中文**

> SysML v2 生成的守门人:分层校验,评测即奖励,作弊过不了关。

SYVERN 是面向 SysML v2 生成任务的统一**校验 / 评测 / 奖励**服务。同一套校验逻辑产出同一份
JSON,贯穿四个用途——SFT 数据过滤、训练评测与回归、RFT 拒绝采样、在线 RLVR 奖励——因此字段口径在
SFT 阶段冻结一次,RL 阶段只调权重。

设计文档:[`doc/syvern_hld.md`](doc/syvern_hld.md)(概要设计)、[`doc/syvern_lld.md`](doc/syvern_lld.md)
(详细设计)、[`doc/sysmlv2_harness_final_design.md`](doc/sysmlv2_harness_final_design.md)(最终方案)、
[`doc/syvern_phase2_design.md`](doc/syvern_phase2_design.md)(二阶段生产化设计)。

> **实现状态:** 本仓库是一个**确定性 harness**,默认在 **stub 后端**之上完整实现设计面(pipeline、
> schema、奖励、抗作弊、监控)。Pilot/Xtext、MontiCore、Imandra/Gamma/nuXmv 与 LLM 裁判的 HTTP
> 适配器 seam 和配置入口已具备——见[实现状态](#实现状态)。

---

## 设计原则

1. **评测 = 奖励** —— 一条校验路径、一份 JSON;SFT 冻结字段语义,RL 仅调权重。
2. **收敛分层** —— 只有确定性核心进确定性奖励:
   - **T0**(解析 / 名称解析 / 类型检查 / 元模型规则)→ 确定性奖励主信号
   - **T1**(结构 F1 / 需求覆盖率 / GED)→ 降权辅助奖励(需冻结参照)
   - **T2**(意图保真,LLM-judge)→ 仅监控 / 偏好,**绝不**进 RLVR 奖励
3. **服务化、无状态、可缓存、幂等** —— 为 RL 在线高吞吐采样而设计。
4. **版本钉死、可复现** —— 后端版本写入指纹并加盖在每条结果上。
5. **抗作弊优先于召回** —— 否决层是硬边界,触发即奖励置零。

---

## 架构

```
                ┌──────────────────────────────────────────────┐
   模型文本  →  │  L0  Pilot 参考实现 (权威主判决)               │ ← 主判决       [stub]
                │  L0' MontiCore 独立第二解析器                  │ ← 交叉一致性   [stub]
                │  L1  元模型派生规则 + 抗作弊                    │ ← T0 + 否决
                │  L2  形式化工具 (Imandra/Gamma/nuXmv)         │ ← 深度,离线   [adapter seam]
                └──────────────────────────────────────────────┘
                                  ↓ 统一 JSON
```

### 校验 Pipeline(逐级 gating)

| 阶段 | 检查 | 收敛层 |
|---|---|---|
| **0 PARSE** | 词法/语法解析成功? | T0 |
| **1 RESOLVE** | 引用可解析到已声明元素? | T0 |
| **2 TYPECHECK** | 类型 / KerML 约束?(不阻断) | T0 |
| **3 CONSTRAINT** | 元模型规则 + 抗作弊 | T0 / 否决 |
| — *以下需参照* — | | |
| **4 STRUCTURAL** | 与参照模型结构匹配 | T1 |
| **5 INTENT** | LLM-judge 意图保真(离线/监控) | T2 |

任一阶段失败,后续标 `reached=false`(「未达到」,区别于 `evaluated=false`「未评估」),天然形成阶梯式
reward shaping。Stage 0–3 不依赖参照,可对任意样本运行。

### 模块

| 文件 | 职责 |
|---|---|
| [`api.py`](src/syvern/api.py) | FastAPI 网关:路由、缓存、记录 |
| [`alignment.py`](src/syvern/alignment.py) | 适配器对齐用例加载与分阶段一致率统计 |
| [`benchmark.py`](src/syvern/benchmark.py) | 本地 `online_reward` 延迟/吞吐基准辅助 |
| [`cache.py`](src/syvern/cache.py) | 校验响应缓存:默认内存 + SQLite 持久化后端 |
| [`cli.py`](src/syvern/cli.py) | 命令行对齐冒烟 runner |
| [`pipeline_factory.py`](src/syvern/pipeline_factory.py) | 按 settings 选择适配器并组合后端指纹 |
| [`pipeline.py`](src/syvern/pipeline.py) | Stage 0–5 编排 / gating 状态机 |
| [`storage_factory.py`](src/syvern/storage_factory.py) | 按 settings 选择 cache / record store |
| [`adapters/`](src/syvern/adapters) | L0 Pilot / L0' MontiCore / L2 形式化 / LLM judge HTTP seam + 确定性 stub |
| [`rules.py`](src/syvern/rules.py) | L1 元模型 + 抗作弊规则(带严重度) |
| [`veto.py`](src/syvern/veto.py) | 硬边界抗作弊否决 |
| [`structural.py`](src/syvern/structural.py) | T1 元素匹配、P/R/F1、需求覆盖率、确定性 GED 准确率 |
| [`ipt.py`](src/syvern/ipt.py) | 同构扰动测试(IPT)一致性 |
| [`intent.py`](src/syvern/intent.py) | T2 确定性意图裁判 |
| [`calibration.py`](src/syvern/calibration.py) | Cohen κ 裁判校准辅助 |
| [`robustness.py`](src/syvern/robustness.py) | `pass@k` / `stable@k` 聚合 |
| [`reward.py`](src/syvern/reward.py) | 统一 JSON → 奖励标量(含否决门) |
| [`monitoring.py`](src/syvern/monitoring.py) | 聚合摘要 + RL 发散检测 |
| [`records.py`](src/syvern/records.py) | 校验事件存储:默认内存 + SQLite 持久化后端 |
| [`settings.py`](src/syvern/settings.py) | 权重、上限、阈值、冻结指纹、环境变量加载 |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI gates: compileall、ruff、mypy、pytest、alignment smoke |

---

## 安装

```powershell
python -m pip install -e ".[test]"
```

需要 Python ≥ 3.11。

## 测试

```powershell
python -m pytest -q
```

## 对齐冒烟

```powershell
syvern align --adapter pilot-stub --dataset data/alignment/stub_smoke.jsonl --min-overall 1.0
syvern align --adapter pilot-stub --dataset data/alignment/stub_smoke.jsonl --min-overall 1.0 --min-parse 1.0 --min-resolve 1.0 --min-typecheck 1.0
syvern align --adapter pilot-stub --dataset data/alignment/stub_smoke.jsonl --min-cases 50 --require-category valid --require-category syntax_error --require-category unresolved_ref --require-category type_error --require-category nested_scale
```

## Online Reward Benchmark

样本文件中每个非空行都会以 `mode="online_reward"` 运行。

```powershell
syvern benchmark --samples data/benchmark/samples.txt --max-average-latency-ms 250 --min-throughput-per-s 4
```

## 运行

```powershell
python -m uvicorn syvern.api:app --reload
```

## 环境变量

API 启动时会从 `SYVERN_...` 环境变量加载 `SyvernSettings`。示例:

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://pilot.local/api"
$env:SYVERN_MONTICORE_ENDPOINT="http://monticore.local/api"
$env:SYVERN_CACHE_PATH="data/syvern-cache.sqlite3"
$env:SYVERN_RECORD_STORE_PATH="data/syvern-records.sqlite3"
$env:SYVERN_RECORD_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_LOG_PATH="data/syvern-audit.sqlite3"
$env:SYVERN_AUDIT_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_SINK_ENDPOINT="http://audit.local/events"
$env:SYVERN_AUDIT_SINK_TIMEOUT_S="2.0"
$env:SYVERN_API_TOKEN="secret-token"
$env:SYVERN_API_READ_TOKEN="read-token"
$env:SYVERN_API_WRITE_TOKEN="write-token"
$env:SYVERN_API_ADMIN_TOKEN="admin-token"
$env:SYVERN_API_RBAC_POLICY='{"read":["read"],"write":["write"],"admin":["read","write","admin"]}'
$env:SYVERN_ENABLE_IDENTITY_RBAC="true"
$env:SYVERN_IDENTITY_RBAC_POLICY='{"sysml-readers":["read"],"sysml-writers":["write"],"sysml-admins":["admin"]}'
$env:SYVERN_ENFORCE_TENANT_ISOLATION="true"
```

奖励权重可用 `SYVERN_WEIGHT_W0` 到 `SYVERN_WEIGHT_W7` 覆盖。

---

## API

| 方法与路径 | 用途 |
|---|---|
| `GET /health` | 存活检查 |
| `POST /validate` | 校验单条 → 统一 JSON |
| `POST /validate_batch` | 批量校验 → 统一 JSON 列表 + `pass@k` / `stable@k` |
| `GET /reward_config` | 当前指纹、权重 `w0..w7`、上限、`r_max`、策略 |
| `GET /audit_events` | 仅 admin 可读的本地鉴权审计流,不记录 token 值 |
| `GET /monitor_summary` | 聚合窗口:通过/否决率、平均奖励/覆盖率/延迟 |
| `GET /dashboard_snapshot` | dashboard 数据快照:聚合 summary、tenant 汇总、最近记录 |

### 模式(mode)

- `online_reward`(默认)—— 仅 L0 + L1,高吞吐。**跳过** L0' 交叉、结构、IPT、意图。
- `full` —— 增加解析器一致性、Stage 4 结构(需 `reference`)、IPT(需 `perturbations`)、Stage 5 意图(需 `intent_reference`)。
- `data_filter` —— Stage 0–3 + 门控阈值。

### 示例

在线奖励(单条):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"online_reward"}'
```

批量鲁棒性:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate_batch -ContentType "application/json" `
  -Body '{"texts":["part A.x","syntax_error","part C.y type_error"],"mode":"online_reward"}'
```

full 模式带参照(结构)、扰动(IPT)、意图:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full",
  "reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},
  {"type":"attribute","qualified_name":"vehicle.mass"}],
  "requirements":["req.power","req.mass"],
  "coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}},
  "perturbations":["attribute vehicle.mass part vehicle.engine"],
  "intent_reference":{"must_include":["vehicle.engine","vehicle.mass"],"must_not_include":["aircraft.wing"]}}'
```

可选 `metadata`(string→string)会被记录用于监控,但不计入缓存键、也不出现在响应中。

### 统一输出 Schema(节选)

```jsonc
{
  "sample_id": "str",
  "tier_summary": { "t0_pass": bool, "t1_available": bool, "veto": bool },
  "stage": {
    "parse":      { "reached": bool, "ok": bool, "parser_agreement": bool|null, "errors": [] },
    "resolve":    { "reached": bool, "ok": bool, "unresolved_refs": int, "errors": [] },
    "typecheck":  { "reached": bool, "ok": bool, "type_errors": int, "errors": [] },
    "constraint": { "reached": bool, "ok": bool, "violations": [{ "rule": "...", "severity": "error|warn" }] }
  },
  "structural": { "evaluated": bool, "precision": 0.0, "recall": 0.0, "f1": 0.0,
                  "requirement_coverage": 0.0, "ged_accuracy": 0.0,
                  "hallucinated_elements": 0, "exact_matched": 0,
                  "normalized_matched": 0, "fuzzy_matched": 0, "soft_matched": 0,
                  "matching_policy_id": "h9-normalized-fuzzy-v1" },
  "robustness": { "stable_at_k": null, "ipt_consistent": null },
  "intent":     { "evaluated": bool, "score": null, "source": "heuristic|llm_judge|human|null" },
  "formal":     { "evaluated": bool, "tool": "imandra|gamma|nuxmv|null",
                  "status": "proved|failed|unknown|timeout|error|null",
                  "properties_checked": 0, "conclusions": [], "counterexamples": [] },
  "veto":       { "triggered": bool, "reason": "str|null" },
  "monitor":    { "codebleu": null, "levenshtein": null },
  "meta":       { "latency_ms": int, "mode": "str", "validator_fingerprint": "str",
                  "reward": 0.0, "text_hash": "str", "cache_hit": bool,
                  "data_filter_pass": bool|null,
                  "data_filter_reason": "passed|t0_failed|vetoed|reward_below_threshold|null" }
}
```

---

## 奖励模型

否决门先于一切;T0 项(`w0..w3`)构成阶梯式主干;T1 覆盖项(`w4..w5`)保留但降权以防空模型;
`intent.score` **绝不**参与计算。

```python
if veto.triggered:
    r = 0.0                                          # 硬边界
else:
    r =  w0 * 1[parse_ok ∧ parser_agreement]         # T0 阶梯
       + w1 * 1[resolve_ok]
       + w2 * (1 - norm(type_errors,  cap_type))
       + w3 * (1 - norm(violations_weighted, cap_cons))
       + w4 * f1_structural                          # T1,降权
       + w5 * requirement_coverage                   # T1,防空模型
       + w6 * 1[ipt_consistent]                      # 可选抗作弊正向项
       - w7 * norm(hallucinated_elements, cap_hall)
    r = clip(r, 0.0, r_max)
```

[`settings.py`](src/syvern/settings.py) 中的默认值:`w0=w1=0.25, w2=w3=0.20, w4=w5=0.05, w6=0.0, w7=0.10, r_max=1.0`。

### 抗作弊否决([`veto.py`](src/syvern/veto.py)、[`rules.py`](src/syvern/rules.py))

`parser_disagreement`(解析器分歧)· `degenerate_output`(token/元素过少却通过校验)·
填充文本(`todo/tbd/???`)· 过度重复 · 占位名(`foo`、`item1` …)· 枚举式作弊。
任一命中 ⇒ `reward = 0`。

---

## 确定性、缓存与监控

- **缓存键** = `(text_hash, validator_fingerprint, mode, reference_id, perturbation_id, intent_reference_id, formal_properties_id)`。
  同键 ⇒ 同结果;指纹变更使旧缓存失效。
- **缓存存储** 是进程内 LRU,带深拷贝隔离和线程锁。
- **在线奖励路径纯确定性** —— 非确定性环节(软语义对齐、LLM 裁判)在 `full` 以外的模式关闭。
- **RL 有效区间监控** —— `detect_divergence` 在两个聚合窗口间标记 `semantic_without_coverage`、
  `veto_rate_increase`、`stable_at_k_drop`(即「合法但空 / 作弊」的 reward hacking 信号)。

---

## 实现状态

pipeline、schema、奖励映射、抗作弊与监控面已全部实现,并由 **282 个通过的测试**验证。里程碑 H1–H6
已按设计基线交付;二阶段切片包括在线 parser-agreement 语义、按 prompt 分组的 stable@k、规范化/模糊结构匹配、
基于原始输出的 IPT 一致性、诚实的 heuristic 意图来源标记、LRU/线程锁缓存与可选 SQLite 后端、显式 data_filter 通过/丢弃决策、
可选 API token 保护、tenant 事件 metadata、可选可信 header 身份组 RBAC、可选 SQLite 鉴权审计事件与可选 HTTP 审计导出、
规则扰动生成器、Pilot/MontiCore HTTP seam、L2 形式化响应与聚合监控、可注入 LLM intent judge seam,以及
settings/env 驱动的后端工厂与指纹组合。设置 `record_store_path`、`audit_log_path` 和 `cache_path` 后,校验事件、审计事件和缓存 payload 都可写入 SQLite 后端,并可用
`record_retention_limit` / `audit_retention_limit` 限制保留的事件数量;设置 `audit_sink_endpoint` 后可 best-effort 导出鉴权审计事件,导出失败不阻塞本地审计或鉴权响应。二阶段状态记录在 [`STATUS.md`](STATUS.md),stub smoke 对齐夹具位于
[`data/alignment/stub_smoke.jsonl`](data/alignment/stub_smoke.jsonl)。

| 里程碑 | 交付内容 | 说明 |
|---|---|---|
| H1 — T0 核心 | Stage 0–3、奖励、缓存、指纹、Pilot HTTP seam | 默认 stub Pilot;可通过 settings 指向 live Pilot |
| H2 — 交叉与鲁棒 | L0' 一致性、`pass@k` / `stable@k`、`/validate_batch`、MontiCore HTTP seam | 默认 stub MontiCore;可通过 settings 指向 live MontiCore |
| H3/H9 — 结构层 | Stage 4、策略 `h9-normalized-fuzzy-v1`、P/R/F1、覆盖率、确定性 GED 准确率、幻觉、exact/normalized/fuzzy/soft 计数 | soft 匹配可通过 HTTP seam 启用 |
| H4/H10 — 抗作弊/IPT | 否决层 + 扰动输出对原始输出的 IPT + 规则规格扰动生成器 | 无 LLM 扰动生成 |
| H5/H11 — 意图与校准 | 确定性 Stage 5 heuristic、可注入 LLM judge seam、Cohen κ 辅助、诚实来源标记 | 默认 heuristic;可通过 settings 指向 live judge |
| H6/H12 — 奖励就绪 | `/reward_config`、`/audit_events`、`/monitor_summary`、`/dashboard_snapshot`、端点发散告警、吞吐冒烟测试、LRU 缓存、env/settings 可选 SQLite cache/record/audit store、记录/审计保留上限、可选 best-effort HTTP 审计导出、data-filter gate、可选 legacy/read/write/admin API token 与可配置 RBAC policy、可选可信 header 身份组 RBAC、tenant 事件 metadata、本地鉴权审计事件、可选 tenant 隔离的监控/dashboard 读面、L2 形式化 seam 与聚合率、后端工厂、对齐 harness、基准辅助、CLI 分阶段/类别对齐门禁、CLI 延迟/吞吐门禁 | API 默认仍为内存/开放；hosted SLA 目标仍需按部署环境给定 |
| G8 — CI | GitHub Actions 工作流:compileall、ruff、mypy、pytest、adapter alignment smoke | 本地 CI gates 已验证 |

**已知简化(设计使然,非缺陷):**

- 默认后端为确定性 **stub**。`syntax_error`、`unresolved_ref`、`type_error`、`parser_disagreement`、
  `summary_disagreement` 等标记驱动各阶段门控,供测试/本地开发用——并非真实 SysML 解析器或等价性证明器。
  设置 `pilot_endpoint`、`monticore_endpoint`、`formal_endpoint`、`intent_judge_endpoint` 或
  `structural_matcher_endpoint` 或 `perturbation_endpoint` 可启用对应 HTTP 适配器。
- `/monitor_summary` 会与上一次端点调用的聚合窗口比较;基线保存在进程内,服务重启会重置。
- 聚合 `stable_at_k` 在提供 `metadata.prompt_id` 时按 prompt 分组;未分组事件按单样本 prompt 处理。
- 未实现:真实后端 >= 50 条对齐数据集、经校准的线上语义对齐匹配、前端仪表盘、部署到真实 IdP/反向代理之后的可信身份 header 接入。

**下一步:** 将已配置的 HTTP adapter seam 指向真实 SysML v2 服务,在部署中配置 `cache_path` / `record_store_path` / 保留上限,并用真实后端输出跑对齐测试集。
