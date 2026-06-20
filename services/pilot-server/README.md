# SYVERN Pilot Server (D1 skeleton)

Minimal resident JVM HTTP service that exposes a SysML v2 parse/resolve/typecheck
backend to SYVERN over HTTP. This is the **D1 skeleton** from
[`doc/syvern_pilot_backend_design.md`](../../doc/syvern_pilot_backend_design.md):
runnable today with a deterministic **stub** backend; the real Pilot
(Xtext/EMF) integration is a seam (`RealPilotBackend`).

> ⚠️ The default `StubPilotBackend` does **not** understand SysML v2 — it mirrors
> the in-repo Python stub (magic markers `syntax_error` / `unresolved_ref` /
> `type_error` + regex element extraction) so the whole path is runnable and
> testable end-to-end before the real parser lands.

## Requirements

- JDK 17+
- Gradle 8.x (or generate the wrapper once: `gradle wrapper`, then use `./gradlew`)

## Run

```bash
cd services/pilot-server
gradle run            # or ./gradlew run after `gradle wrapper`
```

Environment:

- `PILOT_PORT` (default `8080`)
- `PILOT_THREADS` worker pool size (default `8`)
- `PILOT_BACKEND` `stub` (default) or `real` (requires the `-PwithPilot` build, see below)
- `PILOT_VERSION` version string the real backend reports on `/version`

## Test

```bash
gradle test          # JUnit 5 integration smoke test (starts the server on an ephemeral port)
```

`PilotServerSmokeTest` exercises `/health`, `/version`, `/validate` (valid + syntax-error),
the legacy `/parse` route, and the 400/405 error paths.

## API

Primary contract (design doc §3.1):

```
POST /validate   {"text": "<sysml>"} -> { parse, resolve, typecheck, elements, backend_version }
GET  /version    -> { pilot_version, grammar_version, rules_version }
GET  /health     -> { status: "ok" }
```

Legacy contract (compatible with the current SYVERN `PilotAdapter` before the
D2 single-call refactor):

```
POST /parse      -> { ok, errors, elements }
POST /resolve    -> { ok, unresolved_refs, errors }
POST /typecheck  -> { ok, type_errors, errors }
```

## Smoke test

```bash
curl -s localhost:8080/health
curl -s localhost:8080/version
curl -s -X POST localhost:8080/validate \
  -H 'Content-Type: application/json' \
  -d '{"text":"part vehicle.engine attribute vehicle.mass"}'
# parse.ok=true, elements=[{part,vehicle.engine},{attribute,vehicle.mass}]

curl -s -X POST localhost:8080/validate \
  -H 'Content-Type: application/json' \
  -d '{"text":"syntax_error part a"}'
# parse.ok=false, PARSE_SYNTAX_ERROR, elements=[]
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/validate `
  -ContentType "application/json" -Body '{"text":"part vehicle.engine attribute vehicle.mass"}'
```

## Wire into SYVERN

Point SYVERN at this service (the current adapter uses the legacy routes):

```powershell
$env:SYVERN_PILOT_ENDPOINT = "http://127.0.0.1:8080"
$env:SYVERN_PILOT_VERSION  = "stub-0.1.0"
python -m uvicorn syvern.api:app --reload
```

With the stub backend this reproduces SYVERN's stub behaviour over HTTP. Swap
`StubPilotBackend` for `RealPilotBackend` (in `PilotServer.BACKEND`) to get real
SysML v2 judgement.

## Real Pilot backend (H7) — VERIFIED against Pilot 0.59.0

`RealPilotBackend` (in the optional `src/pilotReal/` source set) wraps the
official SysML v2 Pilot via `org.omg.sysml.interactive.SysMLInteractive` (the
same entry point the Jupyter kernel uses): `getSyntaxErrors()` → parse, semantic
errors with code `…Diagnostic.Linking` → resolve, remaining semantic errors →
typecheck, `getRootElement().eAllContents()` → elements.

The Pilot is **not on Maven Central**, but the **SysML v2 Jupyter kernel bundles
it in one fat jar** (`jupyter-sysml-kernel-<ver>-all.jar`). That jar is the
easiest way to build/run the real backend — no source build required.

### Verified recipe (Jupyter-kernel jar)

```powershell
$JAR = "<conda-env>/share/jupyter/kernels/sysml/jupyter-sysml-kernel-0.59.0-all.jar"
$LIB = "<...>/SysML-v2-Release/sysml.library"
$SVC = "services/pilot-server"

# compile main + real backend against the bundled jar (JDK 17)
javac -encoding UTF-8 -cp "$SVC/libs/gson-2.10.1.jar" -d "$SVC/build" (Get-ChildItem "$SVC/src/main/java" -Recurse -Filter *.java).FullName
javac -encoding UTF-8 -cp "$SVC/libs/gson-2.10.1.jar;$JAR;$SVC/build" -d "$SVC/build" (Get-ChildItem "$SVC/src/pilotReal/java" -Recurse -Filter *.java).FullName

# run with the real backend (loads the standard library once, ~6s)
$env:PILOT_BACKEND="real"; $env:SYSML_LIBRARY_PATH=$LIB
java -cp "$SVC/build;$SVC/libs/gson-2.10.1.jar;$JAR" org.syvern.pilot.PilotServer
```

Or via Gradle, pointing at the same jar:

```bash
gradle run -PwithPilot -PpilotJar=/path/to/jupyter-sysml-kernel-0.59.0-all.jar
# (env: PILOT_BACKEND=real, SYSML_LIBRARY_PATH=/path/to/sysml.library)
```

Then point SYVERN at it: `SYVERN_PILOT_BACKEND=pilot`, `SYVERN_PILOT_ENDPOINT=http://127.0.0.1:8080`.

`PilotServer` loads `RealPilotBackend` reflectively, so the default build needs
no Pilot dependency. `PILOT_BACKEND=real` without the `-PwithPilot`/jar build
fails fast with a message pointing here.

> **Note on the corpus:** `data/alignment/pilot_real_corpus.jsonl` was authored
> by hand and is **not yet calibrated** — the real Pilot rejects some of it
> (e.g. untyped `attribute mass;` → "Features must have at least one type",
> `part def` needs the library's `Parts::Part`). Conformant models import or
> fully-qualify library types (`attribute m : ScalarValues::Real;`) or use local
> definitions. Calibrate with `syvern align --adapter pilot --emit-calibrated`.

## Container (B)

Deploy the Pilot service as a container instead of building locally:

```bash
docker build -t syvern-pilot services/pilot-server
docker run -p 8080:8080 -e PILOT_BACKEND=stub syvern-pilot           # stub
# real backend: requires the Pilot artifact reachable to the build (not on Maven Central)
docker build --build-arg WITH_PILOT=1 -v $HOME/.m2:/root/.m2 -t syvern-pilot-real services/pilot-server
docker run -p 8080:8080 -e PILOT_BACKEND=real syvern-pilot-real
```

## Parallel backends (A ∥ B)

The two validation approaches coexist and are selected per mode by SYVERN:

| `SYVERN_PILOT_BACKEND` | online_reward / data_filter (fast L0) | full (authoritative L0) |
|---|---|---|
| `subset` (A) | in-process subset parser | subset (or real Pilot if `SYVERN_PILOT_ENDPOINT` set) |
| `pilot` (B) | real Pilot | real Pilot |
| `stub` (default) | stub | stub (or real Pilot if endpoint set) |

The headline parallel setup — **fast in-process subset for the high-throughput
online path, authoritative real Pilot for full evaluation**:

```powershell
$env:SYVERN_PILOT_BACKEND = "subset"
$env:SYVERN_PILOT_ENDPOINT = "http://127.0.0.1:8080"   # real Pilot container
python -m uvicorn syvern.api:app --reload
```

This mirrors the design's L0' (fast, in-process) ∥ L0 (authoritative) split.

## Layout

```
services/pilot-server/
├── build.gradle / settings.gradle
├── src/main/java/org/syvern/pilot/
│   ├── PilotServer.java       # HTTP routes + worker pool + backend selection
│   ├── PilotBackend.java      # judgement seam
│   ├── StubPilotBackend.java  # deterministic stub (default)
│   ├── Api.java               # wire DTOs (records)
│   └── Json.java              # shared Gson
├── src/test/java/org/syvern/pilot/
│   └── PilotServerSmokeTest.java
└── src/pilotReal/java/org/syvern/pilot/   # built only with -PwithPilot
    └── RealPilotBackend.java  # wraps the SysML v2 Pilot (Xtext/EMF)
```
