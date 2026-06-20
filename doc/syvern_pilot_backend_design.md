# SYVERN 接真 Pilot 适配器 + JVM 服务 设计与开发文档(H7)

> **SYVERN** = *SysML V2 EValuation & Reward eNgine*
> 文档级别:施工级设计 + 开发说明。承接 HLD / LLD / 《阶段二生产化设计》(`syvern_phase2_design.md` §2/§3)与《元素集打通》(`syvern_element_set_wiring_design.md`,已完成)。
> 定位:H7 是把 SYVERN 从"会评分但看不懂 SysML"变成"能真正验证 SysML v2"的**从 0 到 1 关键步**。元素集打通已就位,真元素一旦由本适配器产出即可贯穿全下游。
> 约定:`PilotAdapter`、`ValidatorAdapter`、`ParseResult`、`SyvernSettings` 等符号指现有仓库代码;JSON/接口为设计基线,落地以实际 Pilot 版本输出对齐。

---

## 1. 背景与目标

### 1.1 现状
- **元素集打通已完成**(`7aef4ee`):`parse_result.element_summary` 已贯穿结构/否决/规则/IPT,`extract_element_summary` 仅存于 stub。
- **`PilotAdapter` 已是 HTTP 客户端骨架**([pilot.py](../src/syvern/adapters/pilot.py)):向 `{endpoint}/parse|resolve|typecheck` 发请求,但**没有真实后端服务**;默认仍回落 `PilotStubAdapter`(正则 + 魔法字符串,不懂语法)。
- 红线测试 `test_broken_model_scores_below_valid_with_syntax_aware_adapter` 已证明:**一旦适配器懂语法,合法/损坏即被正确区分**。H7 就是把这个"懂语法的适配器"做成真的。

### 1.2 目标
1. 构建一个**常驻 JVM HTTP 服务**,包装官方 SysML v2 Pilot Implementation(Xtext/EMF),对 `text` 产出真实的解析/名称解析/类型检查结论 + **真元素集** + 归一化错误。
2. **加固 `PilotAdapter`**:单次调用、连接复用、传输错误与验证失败分离、动态指纹、错误码归一化。
3. 建立**对齐语料 + 扩展对齐 harness**(校验元素集),作为接真后端的验收门。

### 1.3 非目标(本阶段不做)
- L2 形式化(Imandra/Gamma/nuXmv)—— 仍走既有 seam,离线/抽样(phase-2 §7)。
- 真 LLM 意图裁判 / 结构软对齐 —— 各自 seam 不变。
- 模糊匹配策略升级 —— 已在 `h9-normalized-fuzzy-v1`,不动。
- 重写 SysML 语义 —— **坚决不自研**,语义层完全交给官方 Pilot。

---

## 2. 架构决策

### 2.1 选型:常驻 JVM + 薄 HTTP 包装(推荐)

| 方案 | 说明 | 取舍 |
|---|---|---|
| **A 常驻 JVM HTTP 服务(选定)** | 包装 `org.omg.sysml.interactive.SysMLInteractive`,进程内一次初始化 Xtext,复用 | 契合现有 `PilotAdapter`;无每条冷启动;语言无关 |
| B JPype/Py4J 进程内桥 | Python 直接载入 Pilot 类 | 省网络,但 Xtext standalone 初始化 + classpath 复杂、与 Python 进程耦合 |
| C Systems Modeling API & Services | 标准 REST 模型仓库 | 面向模型 CRUD,非"诊断文本",不适配验证器用途 |
| D Jupyter kernel 协议 | 复用 Pilot kernel | 有状态、REPL 取向,不适合无状态高吞吐 |

**硬约束(phase-2 §2.2):禁止每条请求冷启动 JVM。** 服务进程常驻,Xtext injector 只初始化一次。

### 2.2 两个交付物
- **D1 JVM 服务**(新仓/子目录 `services/pilot-server/`,Java + Gradle):真正"看懂 SysML"。
- **D2 适配器加固**(仓内 `src/syvern/adapters/pilot.py`):把服务接进 SYVERN,并修掉现有缺陷。

---

## 3. D1 · JVM 服务设计

### 3.1 接口契约(目标:单次 `/validate`,修掉 3× 解析)

> 现状 `PilotAdapter` 发 **3 次独立请求**(parse/resolve/typecheck),后端会解析 3 遍——在线路径不可接受。目标契约改为**一次 `/validate` 返回三段 + 元素**:

```jsonc
POST /validate          Req: { "text": "<sysml source>" }
Resp: {
  "parse":      { "ok": bool, "errors": [Error] },
  "resolve":    { "ok": bool, "unresolved_refs": int, "errors": [Error] },
  "typecheck":  { "ok": bool, "type_errors": int, "errors": [Error] },
  "elements":   [ { "type": "part", "qualified_name": "vehicle.engine" } ],
  "backend_version": "2026.x"
}
// Error = { "code": "RESOLVE_UNRESOLVED_REF", "message": "...", "location": "line:col" }

GET  /version           Resp: { "pilot_version": "...", "grammar_version": "...", "rules_version": "..." }
GET  /health            Resp: { "status": "ok" }
```

### 3.2 内部流程(三个关键映射)

```
text ──▶ SysMLInteractive.eval(text) ──▶ EMF Resource + 诊断
  │
  ├─ parse.errors    ← resource.getErrors()            (语法)        [Stage 0]
  ├─ elements        ← 遍历 EMF 模型树,见 §3.3                       [喂 T1]
  ├─ resolve         ← 链接诊断 / unresolved proxy 计数               [Stage 1]
  └─ typecheck       ← Diagnostician.validate(model) 的 KerML 约束    [Stage 2/3]
```
> 具体 API 名称以实际 build 的 Pilot 版本为准,需对照源码核对。

### 3.3 AST → ElementSummary 映射(核心价值)
遍历 EMF 模型,对每个 `Element` 产出 `{type, qualified_name}`:
- `type` ← 元类名(`eClass().getName()`,如 `PartUsage/AttributeUsage/ConnectionUsage/RequirementUsage/ActionUsage/ItemUsage`)**归一化**到 SYVERN 枚举:`part / attribute / connection / requirement / action / item`(与 [stub.ELEMENT_PATTERN](../src/syvern/adapters/stub.py) 的类型集一致,保证替换等价)。
- `qualified_name` ← `Element.getQualifiedName()`,小写归一化(与 [models.ElementSummary](../src/syvern/models.py) 的 `normalize_non_empty` 规则一致)。
- **必须确定、稳定**:同输入同元素集、同顺序无关(下游用多重集),否则破坏幂等与缓存。

### 3.4 错误归一化(§8 错误码注册表)
不同诊断文案映射到统一 `code` 枚举(如 `PARSE_SYNTAX_ERROR`/`RESOLVE_UNRESOLVED_REF`/`TYPECHECK_MULTIPLICITY`...),便于跨版本比较与 L1 规则匹配。注册表是 SYVERN 与服务的**共享契约**。

### 3.5 并发与性能
- **Worker 池**:Xtext `ResourceSet`/`SysMLInteractive` 非线程安全 → 每 worker 一套,池化处理并发。
- **无状态**:每次 `/validate` 用全新/重置的 ResourceSet,避免跨请求模型残留。
- **目标**:配合 SYVERN 缓存,常见样本 P50 在数十 ms 量级(冷样本受 Pilot 解析耗时支配)。

### 3.6 版本、打包、部署
- `/version` 返回真实 Pilot release tag/commit + 语法/规则集版本 → SYVERN 启动握手写进指纹(§5.4)。
- 构建:克隆官方 Pilot 仓库 Gradle 构建(或取 `org.omg.sysml` Maven 包)+ 包装层 → fat Jar → Docker 镜像,带 `/health` 探针。
- License:Pilot 为 LGPL/Apache,作为独立服务包装合规。

### 3.7 Java 服务骨架(示意)
```java
public final class PilotServer {
  // 启动时一次性初始化(常驻);worker 池各持一套 ResourceSet
  private static final SysMLInteractive SYSML = SysMLInteractive.createInstance();

  static Map<String,Object> validate(String text) {
    var result = SYSML.eval(text);                       // 解析 + 诊断
    return Map.of(
      "parse",     Map.of("ok", syntaxOk(result),     "errors", syntaxErrors(result)),
      "resolve",   Map.of("ok", linkOk(result),       "unresolved_refs", unresolved(result), "errors", linkErrors(result)),
      "typecheck", Map.of("ok", validationOk(result), "type_errors", typeErrorCount(result), "errors", typeErrors(result)),
      "elements",  extractElements(result),             // EMF 遍历 → [{type, qualified_name}]
      "backend_version", VERSION
    );
  }
}
```

---

## 4. D2 · 适配器加固(仓内)

### 4.1 单次调用(修 3× 往返)——least-invasive 方案
保持 `ValidatorAdapter` 协议(`parse/resolve/typecheck` 三方法)不变,**适配器内部对单次 `pipeline.validate` 周期内的同一 `text` 记忆化**:首个 `parse(text)` 触发一次 `/validate`,缓存结果;随后 `resolve(text)`/`typecheck(text)` 命中缓存,不再发请求。

```python
class PilotAdapter:
    def parse(self, text):     return self._analyze(text).parse
    def resolve(self, text):   return self._analyze(text).resolve
    def typecheck(self, text): return self._analyze(text).typecheck

    def _analyze(self, text):                      # 记忆化:同 text 只打一次 /validate
        if self._cache_text != text:
            self._cache = self._post_validate(text)
            self._cache_text = text
        return self._cache
```
> 备选:给协议加 `analyze(text)` 一次性方法 + 改 pipeline 调用。本文选记忆化,因为零协议/零 pipeline 改动、风险最小;且 pipeline 本就按 parse→resolve→typecheck 顺序同 text 调用。
> 注意:适配器实例若被并发复用,需每请求独立实例或加锁(见 §4.5)。

### 4.2 传输错误 vs 验证失败(修当前缺陷)
现状 [pilot.py:33](../src/syvern/adapters/pilot.py) `except Exception → ok=False`,把网络抖动误判成"模型解析失败"→ 误发 0 奖励。**改为区分两类**:
- **验证失败**(后端 200 + `ok=false`):正常流入 stage 判决。
- **传输/后端错误**(超时、5xx、连接失败):抛 `PilotBackendError`;由 pipeline/网关决定**熔断**——标 `stage.reached=false` + 错误码,**不计入奖励/否决**,而非当作真失败。
  - 需在 [models](../src/syvern/models.py) / pipeline 增加"后端不可用"路径(区别于"解析未通过")。

### 4.3 连接复用
`urllib.urlopen` 无连接池 → 换 `requests.Session` 或 `httpx.Client`(keep-alive 连接池),复用 TCP/TLS。超时、重试(幂等 GET/POST 同体可重试)、退避策略入配置。

### 4.4 动态指纹
现状 `fingerprint()` 返回 `pilot@{static_version}`。**改为启动握手**:调 `/version` 取真实版本拼接进 `validator_fingerprint`(`pipeline_factory` 已会拼接后端指纹,见 [pipeline_factory.py:62](../src/syvern/pipeline_factory.py))。版本变更 → 缓存自动失效。握手失败则拒绝启动(避免用错版本污染缓存)。

### 4.5 并发安全
记忆化使适配器有状态。两选一:① 每请求构造轻量适配器(共享 `httpx.Client`);② 记忆化加锁/用 contextvar。推荐 ① + 共享连接池。

---

## 5. 配置项(settings 增补)

| 配置 | 含义 | 现状 |
|---|---|---|
| `pilot_endpoint` | 服务地址 | 已有 |
| `pilot_version` | 过渡期手填版本 | 已有;握手就绪后改为只读校验 |
| `pilot_timeout_s` | 单次超时 | 已有 |
| `pilot_max_retries`(新) | 传输错误重试次数 | 新增 |
| `pilot_fail_open`(新) | 后端不可用时:熔断置 reached=false(false)/降级 stub(true) | 新增,默认 false |

环境变量沿用 `SYVERN_PILOT_*` 命名(见 [settings.py](../src/syvern/settings.py))。

---

## 6. 对齐语料与 harness 扩展(验收前提)

### 6.1 语料(phase-2 §2.5)
建 `data/alignment/pilot_corpus.jsonl`,**≥50 条人工标注 `.sysml`**,覆盖 5 类:`valid / syntax_error / unresolved_ref / type_error / nested_scale`。现仅有 4 行 `stub_smoke.jsonl`。

### 6.2 harness 扩展:校验元素集(关键缺口)
现 [alignment.py](../src/syvern/alignment.py) 的 `AlignmentCase` 只校验 `parse_ok/unresolved_refs/type_errors`,**不校验元素集**——但结构层完全依赖元素正确性。增补:
- `AlignmentCase` 增 `expected_elements: list[tuple[str,str]] | None`;
- `run_adapter_alignment` 增元素多重集比对 + `element_accuracy`;
- CLI `syvern align` 增 `--min-element-accuracy`。

### 6.3 验收命令
```powershell
syvern align --adapter pilot --dataset data/alignment/pilot_corpus.jsonl `
  --min-cases 50 --min-overall 0.95 --min-element-accuracy 0.95 `
  --require-category valid --require-category syntax_error `
  --require-category unresolved_ref --require-category type_error --require-category nested_scale
```

---

## 7. 测试设计

| 类别 | 用例 |
|---|---|
| 适配器单测(mock HTTP) | `/validate` 字段映射;`ok=false` → stage 失败;记忆化只打一次请求 |
| 传输错误 | 超时/5xx → `PilotBackendError` → reached=false(非 ok=false);不污染奖励 |
| 集成(fake server) | 起一个最小 HTTP fake,跑 pipeline 端到端,断言真元素驱动结构/否决/IPT |
| 红线(真适配器) | 复用 `test_broken_model_scores_below_valid...`,把 fake 换成真/集成适配器 |
| 对齐 | §6.3 一致率(含元素)达标 |
| 指纹 | 握手版本写入 `validator_fingerprint`;版本变更触发缓存失效 |
| 性能 | `syvern benchmark` 单次 `/validate` 在线延迟/吞吐达 SLA(单次往返,非 3×) |

---

## 8. 错误码注册表(共享契约,节选)

| code | stage | 触发 |
|---|---|---|
| `PARSE_SYNTAX_ERROR` | parse | 词法/语法错误 |
| `PARSE_EMPTY_INPUT` | parse | 空输入 |
| `RESOLVE_UNRESOLVED_REF` | resolve | 引用无法解析到已声明元素 |
| `TYPECHECK_MULTIPLICITY` | typecheck | 多重度约束违反 |
| `TYPECHECK_FEATURE_TYPING` | typecheck | feature typing/subsetting/redefinition 违反 |
| `PILOT_BACKEND_ERROR` | * | 传输/后端错误(熔断用,不入奖励) |

注册表与 JVM 服务、SYVERN 规则层共享;新增码需双边同步并入指纹考量。

---

## 9. 里程碑与任务拆分

| 序 | 任务 | 依赖 | 可独立验证 |
|---|---|---|---|
| T1 | JVM 服务:`/validate`+`/version`+`/health`,元素抽取 + 诊断映射 | — | 对 fake 输入返回正确 JSON |
| T2 | 适配器:单次 `/validate` 记忆化 + httpx 连接池 | T1 契约 | mock HTTP 单测 |
| T3 | 适配器:传输错误熔断(reached=false 路径)+ pipeline/模型支持 | T2 | 传输错误测试 |
| T4 | 动态指纹握手 + 版本失效 | T1 | 指纹测试 |
| T5 | 错误码注册表(双边) | T1 | 映射测试 |
| T6 | 对齐语料 ≥50 + harness 元素校验 + CLI 阈值 | T1–T5 | `syvern align` 达标 |
| T7 | 性能基准达 SLA | T1–T6 | `syvern benchmark` |

关键路径:T1 → T2 → (T3/T4/T5 并行) → T6 → T7。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Pilot JVM 延迟拖垮在线奖励 | 常驻 + worker 池 + SYVERN 缓存;单次往返;L2/MontiCore 仅抽样 |
| 真后端引入非确定性(版本/环境) | 钉版本 + 指纹握手 + 确定性回归;在线关随机项 |
| EMF→元素映射错位 | §6.2 元素对齐校验作为硬验收门 |
| 传输错误被误判为模型失败 | §4.2 熔断路径 + 测试 |
| Pilot 约束随版本改(自动满足→需显式) | 钉版本;升级即重跑对齐 + 重建基线 |
| 接真后端后仍"收敛≠正确" | 文档与评审写清:H7 只让指标有效,不证明模型对 |

---

## 11. 验收标准

1. JVM 服务对 ≥50 条标注语料:parse/resolve/typecheck 一致率 ≥ 0.95,**元素一致率 ≥ 0.95**。
2. 配 `SYVERN_PILOT_ENDPOINT` 后,合法 vs 语法损坏 SysML 的 `reward` 严格拉开(红线测试用真适配器通过)。
3. 单次 `/validate` 往返(非 3×);`syvern benchmark` 达在线 SLA。
4. 传输错误熔断为 `reached=false`,不污染奖励/否决;有测试覆盖。
5. `validator_fingerprint` 含握手得到的真实 Pilot 版本;版本变更使缓存失效。
6. README / 实现状态同步:L0 由 stub 切换为真 Pilot,`[stub]` → `[real]`。

---

### 一句话总结
H7 = 造一个常驻 JVM 服务把官方 Pilot 的"语义判决 + 真元素集"用一次 `/validate` 暴露出来,再把 `PilotAdapter` 加固成"单次往返、连接复用、传输错误熔断、动态指纹"。元素集打通已铺好管道,**接上这个懂语法的后端,SYVERN 的核心验证能力就从 0 变 1**;能否区分合法与损坏,由对齐语料的元素一致率守门。
