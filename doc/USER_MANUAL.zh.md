# SYVERN 使用手册

本文面向需要安装、运行、调用和运维 SYVERN 的用户。内容基于当前仓库实现状态整理：主服务是 Python/FastAPI 应用，默认调用本机 `http://127.0.0.1:8888` 上的 Pilot HTTP 服务作为真实 SysML v2 L0 解析器；仓库同时包含一个 JVM Pilot HTTP 后端骨架，便于在本机启动或接入真实 SysML v2 Pilot。

## 1. 项目定位

SYVERN 是 SysML V2 Evaluation and Reward Engine，目标是把 SysML v2 生成结果的校验、评估、过滤和奖励计算统一到同一条验证路径中。

典型用途：

- SFT 数据过滤：用 `data_filter` 模式判断样本是否可进入训练集。
- 训练评估与回归：用统一 JSON 对不同模型输出做可复现比较。
- RFT 拒绝采样：用奖励和 veto 规则筛掉不合格输出。
- 在线 RLVR 奖励：用 `online_reward` 模式提供高吞吐、确定性的奖励信号。

当前仓库的公开运行入口已经收敛为 Pilot HTTP 路径。也就是说，SYVERN API、CLI alignment 和 benchmark 默认都会访问本机 8888 端口的 Pilot 服务；仓库内历史 stub/subset 代码仅作为内部测试或参考实现保留，不再作为用户可选调用方式。

## 2. 目录速览

| 路径 | 说明 |
|---|---|
| `src/syvern/api.py` | FastAPI 服务入口，提供校验、批量校验、配置、审计和监控接口 |
| `src/syvern/cli.py` | `syvern` 命令行入口，支持 alignment 和 benchmark |
| `src/syvern/pipeline.py` | 校验 pipeline，负责 parse、resolve、typecheck、constraint、structural、intent、formal 等阶段编排 |
| `src/syvern/pipeline_factory.py` | 构建 Pilot HTTP 主解析器，并组合 MontiCore、formal、LLM judge 等辅助后端 |
| `src/syvern/settings.py` | 配置项、环境变量加载、奖励权重、阈值、安全和存储设置 |
| `src/syvern/models.py` | API 请求和响应 schema |
| `src/syvern/adapters/` | Pilot、MontiCore、formal、intent judge、structural matcher、perturbation 等适配器 |
| `src/syvern/cache.py` | 校验缓存，支持内存和 SQLite |
| `src/syvern/records.py` | 校验记录存储，支持内存和 SQLite |
| `src/syvern/audit.py` | API 鉴权审计事件 |
| `services/pilot-server/` | JVM Pilot HTTP 后端，可接真实 Pilot；SYVERN 默认调用 `127.0.0.1:8888` |
| `data/alignment/` | alignment smoke 数据集 |
| `tests/` | Python 测试 |
| `.github/workflows/ci.yml` | CI：compileall、ruff、mypy、pytest、alignment smoke |

## 3. 环境要求

主服务：

- Python 3.11 或更高版本
- pip

可选 Pilot Server：

- JDK 21 或更高版本。真实 Pilot backend 使用的 SysML v2 Jupyter kernel jar 当前按 Java 21 编译。
- Gradle 8.x，或先生成 Gradle wrapper 后使用 wrapper

## 4. 安装

在仓库根目录执行：

```powershell
python -m pip install -e ".[test]"
```

如果需要本地跑 CI 同等检查，可安装：

```powershell
python -m pip install -e ".[ci]"
```

安装后会得到命令行入口：

```powershell
syvern --help
```

## 5. 启动主服务

启动 SYVERN 主服务前，请确认本机 Pilot 服务已在 8888 端口运行：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8888/health
Invoke-RestMethod -Uri http://127.0.0.1:8888/version
```

默认启动方式：

```powershell
python -m uvicorn syvern.api:app --reload
```

默认服务地址为：

```text
http://127.0.0.1:8000
```

健康检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

预期返回：

```json
{"status":"ok"}
```

## 6. API 快速使用

### 6.1 单条校验

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate `
  -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"online_reward"}'
```

常用请求字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 待校验的模型文本 |
| `mode` | `online_reward` / `full` / `data_filter` | 校验模式，默认 `online_reward` |
| `reference` | object | full 模式下结构匹配参考模型 |
| `perturbations` | string array | full 模式下 IPT 扰动后的模型输出 |
| `intent_reference` | object | full 模式下意图参考 |
| `formal_properties` | string array | full 模式下传给 formal adapter 的性质列表 |
| `metadata` | string map | 记录用元数据，不进入缓存键，也不返回给调用方 |

### 6.2 批量校验

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate_batch `
  -ContentType "application/json" `
  -Body '{"texts":["part A.x","syntax_error","part C.y type_error"],"mode":"online_reward"}'
```

批量响应会包含：

- `sample_count`
- `pass_at_k`
- `stable_at_k`
- `responses`
- `meta.mode`
- `meta.validator_fingerprint`

### 6.3 full 模式示例

`full` 模式会在条件满足时额外执行解析器一致性、结构匹配、IPT、intent 和 formal 分析。

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate `
  -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full",
  "reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},
  {"type":"attribute","qualified_name":"vehicle.mass"}],
  "requirements":["req.power","req.mass"],
  "coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}},
  "perturbations":["attribute vehicle.mass part vehicle.engine"],
  "intent_reference":{"must_include":["vehicle.engine","vehicle.mass"],"must_not_include":["aircraft.wing"]}}'
```

## 7. API 端点

| 方法与路径 | 权限范围 | 说明 |
|---|---|---|
| `GET /health` | 无 | 存活检查 |
| `POST /validate` | `write` | 校验单条样本，返回统一 JSON |
| `POST /validate_batch` | `write` | 批量校验，返回统一 JSON 列表和鲁棒性聚合指标 |
| `GET /reward_config` | `read` | 查看 fingerprint、权重、caps、阈值和策略 |
| `GET /audit_events` | `admin` | 查看本地鉴权审计事件，不记录 token 明文 |
| `GET /monitor_summary` | `read` | 查看聚合监控窗口和 divergence alert |
| `GET /dashboard_snapshot?limit=20` | `read` | 查看 dashboard 用快照：summary、tenant 汇总、最近记录 |

默认未配置 token 时，除 `/health` 外的接口也是开放的。配置 token 或 identity RBAC 后，权限范围开始生效。

## 8. 校验模式

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `online_reward` | 在线 RL 奖励、低延迟批量采样 | 只走高吞吐确定性路径，默认 L0 + L1；跳过 MontiCore 一致性、结构、IPT、intent |
| `data_filter` | SFT 或数据清洗 | 基于 T0、veto 和 `data_filter_min_reward` 给出 `data_filter_pass` 与原因 |
| `full` | 离线评估、回归、诊断 | 增加 MontiCore 一致性、结构匹配、IPT、intent、formal 等可选评估 |

## 9. 响应解读

`/validate` 返回 `ValidateResponse`。重点字段如下：

| 字段 | 说明 |
|---|---|
| `sample_id` | 文本 SHA-256，当前与 `meta.text_hash` 一致 |
| `tier_summary.t0_pass` | parse、resolve、typecheck、constraint、veto 后的 T0 是否通过 |
| `tier_summary.t1_available` | 是否完成结构匹配 |
| `tier_summary.veto` | 是否触发反作弊 veto |
| `stage.parse` | 解析阶段结果，full 模式下含 `parser_agreement` |
| `stage.resolve` | 引用解析结果 |
| `stage.typecheck` | 类型检查结果和错误数 |
| `stage.constraint` | 元模型规则和反作弊规则 violations |
| `structural` | 结构匹配 P/R/F1、需求覆盖率、GED 准确率、幻觉元素等 |
| `robustness.ipt_consistent` | IPT 是否一致 |
| `intent` | 意图评价结果，默认 heuristic，可切到 LLM judge |
| `formal` | formal adapter 分析结果 |
| `veto` | veto 是否触发和原因 |
| `meta.reward` | 奖励标量 |
| `meta.cache_hit` | 是否命中缓存 |
| `meta.data_filter_pass` | data_filter 模式下是否通过 |
| `meta.data_filter_reason` | data_filter 模式下的通过或拒绝原因 |

阶段 gating 规则：前置阶段失败时，后续阶段会标记 `reached=false`，这和“已执行但未通过”不同。

## 10. 奖励与 veto

奖励由 `src/syvern/reward.py` 计算，权重来自 `SyvernSettings.weights`：

| 权重 | 默认值 | 含义 |
|---|---:|---|
| `w0` | 0.25 | parse 通过 |
| `w1` | 0.25 | resolve 通过 |
| `w2` | 0.20 | typecheck 错误归一化惩罚 |
| `w3` | 0.20 | constraint violations 归一化惩罚 |
| `w4` | 0.05 | structural F1 |
| `w5` | 0.05 | requirement coverage |
| `w6` | 0.00 | IPT consistency |
| `w7` | 0.10 | hallucinated elements 惩罚 |

`r_max` 默认是 `1.0`。任一硬 veto 触发时，奖励直接归零。

常见 veto 来源：

- parser disagreement
- 输出太短但通过语义路径
- `todo`、`tbd`、`???` 等填充文本
- 过度重复
- `foo`、`item1` 等占位名
- 枚举式投机输出

## 11. 命令行工具

### 11.1 alignment smoke

```powershell
syvern align --adapter pilot --dataset data/alignment/pilot_real_corpus.jsonl --min-overall 0.0 --min-parse 1.0
```

可加更严格门槛：

```powershell
syvern align --adapter pilot `
  --dataset data/alignment/pilot_real_corpus.jsonl `
  --min-overall 0.0 `
  --min-parse 1.0 `
  --min-resolve 1.0 `
  --min-typecheck 1.0
```

可要求数据集覆盖指定类别：

```powershell
syvern align --adapter pilot `
  --dataset data/alignment/pilot_real_corpus.jsonl `
  --min-cases 50 `
  --require-category valid `
  --require-category syntax_error `
  --require-category unresolved_ref `
  --require-category type_error `
  --require-category nested_scale
```

支持的 adapter：

| adapter | 说明 |
|---|---|
| `pilot` | HTTP Pilot adapter，默认调用 `http://127.0.0.1:8888` |

生成待人工复核的校准语料：

```powershell
syvern align --adapter pilot `
  --dataset data/alignment/pilot_real_corpus.jsonl `
  --emit-calibrated data/alignment/pilot_real_calibrated.jsonl
```

### 11.2 online reward benchmark

每个非空行都会以 `online_reward` 模式校验：

```powershell
syvern benchmark --samples data/benchmark/samples.txt
```

可设置门槛：

```powershell
syvern benchmark --samples data/benchmark/samples.txt `
  --max-average-latency-ms 250 `
  --min-throughput-per-s 4
```

注意：当前仓库文件列表中未看到 `data/benchmark/samples.txt`，使用 benchmark 前需要准备该样本文件。

## 12. 配置与环境变量

SYVERN 启动时读取 `SYVERN_...` 环境变量。PowerShell 示例：

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://127.0.0.1:8888"
$env:SYVERN_CACHE_PATH="data/syvern-cache.sqlite3"
$env:SYVERN_RECORD_STORE_PATH="data/syvern-records.sqlite3"
$env:SYVERN_RECORD_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_LOG_PATH="data/syvern-audit.sqlite3"
$env:SYVERN_AUDIT_RETENTION_LIMIT="10000"
python -m uvicorn syvern.api:app --reload
```

常用配置：

| 环境变量 | 说明 |
|---|---|
| `SYVERN_PILOT_ENDPOINT` | Pilot HTTP 服务地址，默认 `http://127.0.0.1:8888` |
| `SYVERN_PILOT_VERSION` | Pilot 版本标识 |
| `SYVERN_PILOT_TIMEOUT_S` | Pilot 超时秒数 |
| `SYVERN_MONTICORE_ENDPOINT` | MontiCore HTTP 服务地址 |
| `SYVERN_FORMAL_ENDPOINT` | formal HTTP 服务地址 |
| `SYVERN_FORMAL_TOOL` | `imandra`、`gamma` 或 `nuxmv` |
| `SYVERN_INTENT_JUDGE_ENDPOINT` | LLM intent judge 服务地址 |
| `SYVERN_STRUCTURAL_MATCHER_ENDPOINT` | LLM structural matcher 服务地址 |
| `SYVERN_PERTURBATION_ENDPOINT` | LLM perturbation generator 服务地址 |
| `SYVERN_CACHE_PATH` | SQLite cache 文件路径；未设置则用内存 |
| `SYVERN_CACHE_MAX_SIZE` | cache 最大条目数 |
| `SYVERN_RECORD_STORE_PATH` | SQLite validation record 文件路径；未设置则用内存 |
| `SYVERN_RECORD_RETENTION_LIMIT` | validation record 保留上限 |
| `SYVERN_AUDIT_LOG_PATH` | SQLite audit event 文件路径；未设置则用内存 |
| `SYVERN_AUDIT_RETENTION_LIMIT` | audit event 保留上限 |
| `SYVERN_AUDIT_SINK_ENDPOINT` | 外部 HTTP 审计导出地址 |
| `SYVERN_ENFORCE_TENANT_ISOLATION` | 是否强制请求带 `X-SYVERN-Tenant` |

奖励权重可用 `SYVERN_WEIGHT_W0` 到 `SYVERN_WEIGHT_W7` 覆盖。

布尔环境变量接受：

```text
1, true, yes, on, 0, false, no, off
```

## 13. Pilot 后端

SYVERN 侧不再提供 stub/subset L0 调用方式。主解析器固定为 Pilot HTTP adapter；不设置环境变量时默认访问本机 8888 端口：

```powershell
python -m uvicorn syvern.api:app --reload
```

如需覆盖地址，设置 `SYVERN_PILOT_ENDPOINT`：

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://127.0.0.1:8888"
python -m uvicorn syvern.api:app --reload
```

如果 Pilot 服务不可达，`/validate` 会返回后端不可用错误；这类错误不会被当作模型输出失败来计算 reward。

## 14. 可选 Pilot Server

首次使用时，复制本机配置模板并填写真实路径：

```powershell
Copy-Item scripts/pilot-real.local.example.ps1 scripts/pilot-real.local.ps1
notepad scripts/pilot-real.local.ps1
```

`scripts/pilot-real.local.ps1` 中需要设置：

```powershell
$JAR = "C:\path\to\jupyter-sysml-kernel-0.59.0-all.jar"
$LIB = "C:\path\to\SysML-v2-Release\sysml.library"
$PILOT_PORT = "8888"
```

这个 local 文件已被 `.gitignore` 忽略，适合放你本机的绝对路径。启动真实 Pilot Server：

```powershell
.\scripts\start-pilot-real.ps1
```

SYVERN 默认调用 `8888` 端口。另开一个 PowerShell 做健康检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8888/health
Invoke-RestMethod -Uri http://127.0.0.1:8888/version
```

校验示例：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8888/validate `
  -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass"}'
```

Pilot Server 环境变量：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PILOT_PORT` | `8080` | HTTP 端口 |
| `PILOT_THREADS` | `8` | worker 线程数 |
| `PILOT_BACKEND` | `stub` | `stub` 或 `real` |
| `PILOT_VERSION` | 服务内部版本 | `/version` 返回的版本标识 |
| `SYSML_LIBRARY_PATH` | 无 | real backend 使用的 SysML library 路径 |

把 Pilot Server 接入 SYVERN：

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://127.0.0.1:8888"
python -m uvicorn syvern.api:app --reload
```

真实 Pilot backend 需要 SysML v2 Jupyter kernel 打包 jar，不在 Maven Central。详细构建方式见 `services/pilot-server/README.md`。

## 15. 安全、RBAC 与租户

### 15.1 Token 鉴权

默认未配置 token 时接口开放。配置后可使用 `Authorization: Bearer ...` 或 `X-SYVERN-API-Key`。

```powershell
$env:SYVERN_API_READ_TOKEN="read-token"
$env:SYVERN_API_WRITE_TOKEN="write-token"
$env:SYVERN_API_ADMIN_TOKEN="admin-token"
python -m uvicorn syvern.api:app --reload
```

调用示例：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/reward_config `
  -Headers @{ Authorization = "Bearer read-token" }
```

默认权限：

| 角色 | 权限 |
|---|---|
| `read` | `read` |
| `write` | `write` |
| `admin` | `read`、`write`、`admin` |

可用 JSON 覆盖：

```powershell
$env:SYVERN_API_RBAC_POLICY='{"read":["read"],"write":["write"],"admin":["read","write","admin"]}'
```

### 15.2 Trusted-header identity RBAC

如果服务部署在可信网关或 IdP 后面，可启用基于 header 的身份组授权：

```powershell
$env:SYVERN_ENABLE_IDENTITY_RBAC="true"
$env:SYVERN_IDENTITY_RBAC_POLICY='{"sysml-readers":["read"],"sysml-writers":["write"],"sysml-admins":["admin"]}'
```

请求 header：

- `X-SYVERN-User`
- `X-SYVERN-Groups`

注意：这些 header 必须只由可信上游注入，不能直接暴露给公网客户端伪造。

### 15.3 租户隔离

开启租户隔离：

```powershell
$env:SYVERN_ENFORCE_TENANT_ISOLATION="true"
```

开启后，validation、monitor、dashboard 相关接口需要：

```text
X-SYVERN-Tenant: tenant-a
```

监控和 dashboard 聚合会按租户过滤。

## 16. 缓存、记录与监控

缓存键由以下部分组成：

```text
(text_hash, validator_fingerprint, mode, reference_id, perturbation_id, intent_reference_id, formal_properties_id)
```

含义：

- 同一个键应返回同一个校验结果。
- fingerprint 改变会自然隔离旧缓存。
- `metadata` 不参与缓存键。

推荐生产配置：

```powershell
$env:SYVERN_CACHE_PATH="data/syvern-cache.sqlite3"
$env:SYVERN_RECORD_STORE_PATH="data/syvern-records.sqlite3"
$env:SYVERN_RECORD_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_LOG_PATH="data/syvern-audit.sqlite3"
$env:SYVERN_AUDIT_RETENTION_LIMIT="10000"
```

查看聚合监控：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/monitor_summary
```

查看 dashboard 快照：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/dashboard_snapshot?limit=20"
```

`/monitor_summary` 会把当前窗口与上一次同 scope 调用的窗口比较，产生 divergence alert。服务重启后该基线会重置。

## 17. 测试与 CI

本地测试：

```powershell
python -m pytest -q
```

本地模拟 CI 关键步骤：

```powershell
python -m compileall -q src tests
python -m ruff check src tests
python -m mypy src
python -m pytest -q
syvern align --adapter pilot --dataset data/alignment/pilot_real_corpus.jsonl --min-overall 0.0 --min-parse 1.0
```

Pilot Server 测试：

```powershell
Set-Location services/pilot-server
gradle test
```

## 18. 常见问题

### 为什么 `/validate` 返回 Pilot backend unavailable？

当前 SYVERN 默认依赖本机 `http://127.0.0.1:8888` 的 Pilot HTTP 服务。如果该服务未启动、端口不一致、`SYVERN_PILOT_ENDPOINT` 配错或 Pilot 处理超时，SYVERN 会把它视为后端不可用，而不是把模型输出误计为 reward 0。

### 为什么 `online_reward` 没有结构匹配和 intent？

`online_reward` 是高吞吐确定性路径，避免在线 RL 奖励引入非确定性或高延迟组件。结构、IPT、intent、formal 等诊断适合 `full` 模式。

### 为什么响应里 `cache_hit=true` 但仍然新增了记录？

API 命中缓存后仍会把本次调用作为 validation record 记录下来，用于监控、dashboard 和租户聚合。

### 为什么 `/monitor_summary` 的 alert 会变？

该接口会和上一次调用的聚合窗口比较。第一次调用通常没有历史窗口；服务重启后历史窗口也会清空。

### 为什么开启租户隔离后请求失败？

开启 `SYVERN_ENFORCE_TENANT_ISOLATION=true` 后，validation、monitor、dashboard 相关请求必须携带非空 `X-SYVERN-Tenant` header。

### benchmark 命令找不到样本文件怎么办？

当前仓库未包含 `data/benchmark/samples.txt`。新建一个文本文件，每行放一个待校验样本，然后把 `--samples` 指向该文件。

## 19. 当前已知边界

- 主 L0 解析器固定为 Pilot HTTP 服务，默认 `http://127.0.0.1:8888`；历史 stub/subset 适配器不再作为公开调用方式。
- 真实 Pilot alignment 数据集仍需校准，`data/alignment/pilot_real_corpus.jsonl` 不是最终金标。
- hosted SLA 阈值需要等真实后端延迟目标确定后再配置。
- 前端 dashboard 尚未实现；当前提供的是 dashboard JSON surface。
- trusted-header identity RBAC 需要真实部署在可信反向代理或 IdP 后面。

## 20. 推荐上手路径

1. 安装：`python -m pip install -e ".[test]"`。
2. 跑测试：`python -m pytest -q`。
3. 确认本机 Pilot 服务在 8888 端口运行：`Invoke-RestMethod -Uri http://127.0.0.1:8888/health`。
4. 启动主服务：`python -m uvicorn syvern.api:app --reload`。
5. 调 `/health` 和 `/validate` 确认主链路可用。
6. 跑 alignment smoke：`syvern align --adapter pilot --dataset data/alignment/pilot_real_corpus.jsonl --min-overall 0.0 --min-parse 1.0`。
7. 部署前配置 SQLite cache、record、audit 路径和必要的 token/RBAC/tenant 策略。
