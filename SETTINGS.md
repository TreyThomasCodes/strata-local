# Settings and rationale

This configuration targets the original rig: Linux, Ryzen 7 5800X, 128 GB RAM,
and two NVLink RTX 3090s with 24 GB VRAM each. It is not a hardware-sizing preset.

Engine settings live in [config/strata-iq3_s.json](config/strata-iq3_s.json).
Build and service settings live in [compose.yaml](compose.yaml). Host paths,
GPU UUIDs, power caps, and port binding come from `.env`.

**Basis:** operator rationale explains the choices. Local tests support specific
operating points, not universal optima. Inherited settings are labeled below.
Evidence IDs refer to the local records listed at the end.

## Model and vision

**IQ3_S follows the recommendation for RAM/VRAM-rich rigs.** The operator chose it
because this rig has ample memory. The pinned upstream [model guide](vendor/Strata/docs/MODELS.md#pick-by-ram)
recommends IQ3_S or UD-IQ4_XS for hosts with at least 96 GB RAM. Local tests used
the existing IQ3_S artifacts; they did not establish a quantization winner.

**Vision is disabled to leave more VRAM for model layers.** This is intentional,
not a missing dependency. `BUILD_VISION=0` builds the text-only deployment.
No local vision-on versus vision-off comparison was found.

## GPU topology and power

**The multi-GPU layout serves thermal goals, not peak throughput.** The cards are
stacked: physical GPU0 draws physical GPU1's hot exhaust. Forward peer mode
makes GPU0 the busier primary. Reversing the roles moves the heavier workload to
the cooler physical GPU1.

| Setting | Value | Role |
| --- | --- | --- |
| `PRIMARY_GPU_UUID` | Physical GPU1's UUID on the original rig | Logical CUDA0; main engine work |
| `PEER_GPU_UUID` | Physical GPU0's UUID on the original rig | Logical CUDA1; peer expert cache and prompt helper |
| `--peer-device` | `1` | Select the logical peer, not host GPU index 1 |
| `PRIMARY_POWER_W` | `300` | Limit the busier card's heat |
| `PEER_POWER_W` | `350` | Retain the tested peer ceiling; not a constant draw |
| `--peer-reserve-mib` | `3072` | Leave room for peer prompt buffers |

UUID ordering preserves roles when GPU enumeration changes. After hardware
replacement, identify the cards again; do not copy host indices blindly.

The reversed-peer screen measured 99.17 tok/s narrative and 129.61 tok/s code
at primary 300 W. Decode peaks were 77/80 C; long-prompt peaks were 79/81 C
(physical GPUs 0/1). No thermal capping was sampled in that arm. All 90K/240K
recall checks passed. The 350 W reversed arm ran faster but showed substantial
thermal capping. The longer v0.1.38 suite also found no sampled thermal limiting
at the selected 300 W operating point. (E2, E3, E7)

Reversal did not prove a speed advantage over forward peer: the 300 W results
were within baseline drift. It drew more combined board power in that screen.
Layer split remained faster for long-context prefill. The operator accepted
these tradeoffs for thermal reasons. No test measured component lifespan.

**The 3072 MiB reserve enables peer prompt offload.** With the default reserve,
startup reported insufficient prompt-buffer space. At 3072 MiB, startup
confirmed P2P prompt offload and about 2349 MiB free after buffer allocation.
The peer cache held fewer experts: 10574 versus 11837. This is a buffer/cache
tradeoff, not evidence that 3072 is the smallest working reserve. (E1)

See the pinned [peer-tier guide](vendor/Strata/docs/SECOND_GPU.md#peer-tier---peer-device)
for the mechanism. Peer mode and layer split are separate modes; do not combine
them.

## Context and KV cache

| Setting | Value | Basis |
| --- | --- | --- |
| `--max-context` | `262144` | Validated native capacity; no RoPE scaling |
| `--kv` | `int8` | Operator's precision/memory tradeoff |
| `--kv-resident` | `32768` | Larger residency failed to show a useful gain |

**INT8 KV saves storage while retaining near-FP16 precision.** The operator chose
it as nearly lossless versus FP16, with roughly half the KV storage. That is not
half of total server VRAM: weights, expert caches, buffers, and metadata remain.
The local records do not contain an INT8-versus-FP16 quality comparison.

**KV residency keeps a working window in VRAM while the larger cache lives in
host RAM.** This leaves VRAM for experts without reducing the configured context.
The pinned [KV-streaming guide](vendor/Strata/docs/DETAILS.md) describes the path.

The local 32768/49152/65536 residency sweep passed all 16 recall checks. Larger
windows showed no useful long-context gain on the synthetic workload and
removed 96/195 primary expert slots, about 199/396 MiB of cache. The report
recommended retaining 32768. This is a measured tradeoff, not universal
optimality. (E6)

**The native 262144-token setting passed long-input checks.** Initial validation
completed roughly 246K-token inputs with all nine positional recall checks
passing. Later reversed-peer and v0.1.39 screens passed 90K/240K recall checks.
The exact context boundary and broad reasoning quality at 256K were not tested.
Leave room for output tokens. (E2, E4, E8)

## Expert execution and speculation

| Setting | Value | Basis |
| --- | --- | --- |
| `--expert-cache` | `auto` | Retained saved setting; no manual-budget winner recorded |
| `--prefill` | `auto` | Retained saved setting; no manual-mode winner recorded |
| `--pcie-frac` | `0.20` | Retained after calibration candidates failed the adoption gate |
| `--spec-min-p` | `0.70` | Existing value also selected by local calibration |
| `--spec` | `4` | Inherited MTP window; not locally optimized |
| `--mtp` | `/models-data/mtp/rt` | Prepared speculative draft tensors |

**PCIe fraction controls the share of uncached host experts sent to the GPU
instead of computed on the CPU.** It does not control NVLink peer traffic.
Short-prompt calibration proposed .35 for split and .00 for peer, both with
confidence .70. Against the saved .20/.70 baseline, neither candidate cleared
the >3% adoption gate on canonical narrative/code workloads. The peer .00
candidate was slower in that screen. Keep .20; do not apply a calibration gain
measured against different defaults to this saved baseline. (E5)

**Draft confidence .70 controls whether the draft layer adds another guess.**
Calibration selected the existing .70 value in both topologies. The follow-up
comparison held it fixed; it did not isolate the threshold's effect. (E5)

**MTP4 is inherited.** The tests exercised it but did not compare speculative
windows. Do not describe 4 as the fastest or most accurate setting for this rig.

## Prompt checkpoints and conversation parking

**Normal prompt checkpoints preserve reusable prefixes.** No `--prompt-cache 0`
override is set. Parking depends on prompt caching; disabling checkpoints also
disables parking. See the pinned [conversation-cache details](vendor/Strata/docs/DETAILS.md).

**Parking avoids repeated full prefill when conversations alternate.** The
operator enabled it for multiple ongoing chats or agent conversations. Parking
is separate from active concurrency; the later `parallel: 2` trial is below.

- `--conversation-cache-mib 16384`: a 16 GiB host-RAM ceiling, not an upfront
  allocation or a VRAM budget.
- `--conversation-cache-slots 8`: up to eight parked conversations, subject to
  the byte budget.
- Exact token/image prefixes and matching steering mode determine reuse.
  Snapshots are memory-only and disappear on restart.

**The budget and slot count are sensible operator defaults, not tuned limits.**
The README records a 2026-10-05 A → B → A smoke test: 1984 of 1991 prompt tokens
restored, with the same deterministic answer. It does not establish sustained
multi-client performance, long-context parking capacity, or an optimal budget.
The older performance and quality matrices ran with parking disabled.

## Build and version

**Strata v0.1.41 is pinned; the tested image was promoted after operator
approval.** Build, server tests, a four-boot comparison against .40.3 and live
promotion checks passed. The peer-mode two-slot/batch-MTP baseline, all other
engine settings and GPU caps remain unchanged; experimental opt-ins remain
off. Both services use the .41 image; the engine reports 0.1.41. No material
speed gain was established. Full quality, broader concurrency and sustained-load
validation remain pending.

The older quality-screen and serial baseline results below remain specific to
their versions. The .41 screen exercises compatibility and the long/long/short
deadlock shape, not comprehensive model quality, fairness or recovery behavior.

**Earlier measurements remain version-specific.** The v0.1.39 screen
measured 108.17/139.55 tok/s narrative/code versus 99.74/129.70 for the combined
v0.1.38 baseline. Cold 240K prefill measured 2308.1 versus 1967.0 tok/s. The
thinking-off quality screen scored 64/75 versus 63/75; one case does not prove
better model quality. All eight long-context recall checks passed. (E8)

CUDA 13.0, sm_86, and native CPU defaults match the tested build. sm_86 targets
the RTX 3090 architecture. No compiler-tuning comparison was recorded. Rebuild
on the destination CPU; the source pin does not freeze base images or packages.

### Peer-mode prefill-chunk sweep (2026-10-08)

**Keep `--prefill auto`. Fixed 4096 improves responsiveness but costs ingestion
speed and peer thermal margin; 2048 costs substantially more.** Six fresh boots
used auto → 4096 → 2048 → 2048 → 4096 → auto. Only --prefill changed; .41 image,
source/profile, peer mode, parallel=2, batch-MTP, context/KV, parking, UUID order
and caps stayed fixed. Normal API traffic was excluded. No candidate adopted.
(E18)

Means across two boots:

| Metric | auto: 8192 selected | 4096 | 2048 |
| --- | ---: | ---: | ---: |
| Short first token beside 90K, s | 7.00 | 4.20 | 2.83 |
| Same short completion, 256 tokens, s | 16.39 | 14.05 | 11.02 |
| Mixed 90K long completion, s | 43.26 | 47.50 | 57.86 |
| Cold 90K recall wall, s | 35.25 | 40.30 | 50.45 |
| Cold 240K recall wall, s | 104.93 | 120.50 | 152.42 |
| Solo narrative / code, tok/s | 121.34 / 136.59 | 120.07 / 132.35 | 117.56 / 134.53 |
| Pair aggregate narrative / code, tok/s | 127.43 / 137.69 | 124.80 / 137.52 | 125.83 / 137.75 |

4096 reduced mixed short TTFT 40%, but cold ingestion wall rose 14–15%. 2048
reduced TTFT 60%, but cold wall rose 43–45%. Replay was effectively flat; it
produced only 12–13 recall tokens, not long outputs. Ordinary decode did not
gain. Modest decode differences are subject to sampled-output/run variation.
Each setting had eight scored solos and six scored pairs per workload after
warmups, 512-token caps, .6/.95/top_k20/min_p0, thinking off.

**Smaller chunks did not reliably solve three-request admission waits.** Four
long/long/short repetitions per setting returned correct answers. Short walls:
auto 6.06–78.42 s, 4096 3.41–87.01 s, 2048 2.05–107.07 s. Each triple recorded
three requests in flight and a control waiter. These sparse maxima are not p95.

**Fixed chunks worsened observed peer thermal behavior on both boots.** Physical
GPU0 peer core peaks were auto 79/82 C, 4096 84/84 C, 2048 85/85 C.
Peer thermal-active samples were 0/0, 60/118 and 348/348 respectively. One primary software
thermal-slowdown sample occurred in the first 4096 arm. Primary core peaked at
81 C; available RAM floor 46.30 GiB. Caps remained primary 300 W / peer 350 W;
no safety guard triggered. Thermal effects and different arm durations limit
isolated chunk-cost attribution. Core readings do not establish memory-junction
temperatures. A latency gain alone does not meet this rig's thermal rationale.

- All six arms completed 52/52 expected inference requests, without counter
  reset or unexpected engine/container restart. Runtime differed only in
  --prefill; serving slots, UUID order, image and profile matched. Batch-MTP
  acceptance and simultaneous two-slot decoding were proved.
- All 12 cold 90K/240K recalls and 12 replays passed. Cold cache_n=0; document
  hashes and actual lengths matched across settings: 90063/240066 tokens.
- Parking restored 2154 tokens. Background arithmetic/sorting/JSON, cancellation
  isolation, post-cancel arithmetic and named tool-call parsing passed; the tool
  was not executed. All mixed code streams in this comparison produced 256
  tokens and had code-module content matching the requested subject.
- Auto borrowed 2305 primary cache slots / 4.38 GiB for prompt buffers; 4096
  borrowed 1514 / 2.87 GiB, 2048 1118 / 2.12 GiB. Matched mixed reads yielded
  at 16384/8192/4096 tokens. Chunk size is not an end-to-end latency guarantee.
- Primary cache stayed 7589 experts / 14740 MiB. Startup free VRAM stayed
  445–447 MiB; the low-headroom warning remains. No cuBLAS error or CUDA-graph
  eviction was logged in the corrected screen.

The earlier attempt was excluded after a 4096 mixed code stream stopped normally
at 26 rather than 256 tokens and tripped the fixed-length benchmark assertion.
The engine did not crash; auto was restored. Its full reply was not archived,
so the answer's quality cannot be classified. The new harness captures the
reply before assessing length; the early stop did not recur in the six-arm run.
Do not call the first response proved corruption or proved harmless EOS.

Auto/two-slot production was restored unchanged; both services healthy, runtime,
GPU order, authenticated arithmetic/metrics and cap readback passed. Five unit
tests, real Compose validation, diff whitespace and credential checks passed.
Source/image, models, key, volume and binding unchanged. No build/server-suite
rerun: the image did not change.

Limits: two boots/setting, fixed balanced order, small synthetic samples, thermal
effects, no full thinking-on/agent quality, 240K concurrent ingestion or
hour-scale per-setting soak. Chunk geometry changes output rounding; no byte-identity
claim. Keep auto for the current thermal/throughput goals. 4096 is an optional
responsiveness tradeoff, not a new default.

### Peer-mode active-slot sweep (2026-10-08)

**Two slots remain the baseline. Three are a workload-specific tradeoff; four
failed the compatibility gate.** The only setting varied was top-level parallel,
with peer mode, batch-MTP, .41 image/source, profile, context/KV, parking and caps
fixed. Six fresh boots used 2 → 3 → 4 → 4 → 3 → 2. Production was restored after
the first four-slot failure, then the reverse half ran. This is balanced but
not uninterrupted or randomized. (E17)

Means across two boots, narrative/code tok/s:

| Metric | 2 slots | 3 slots | 4 slots: short workloads only; rejected |
| --- | ---: | ---: | ---: |
| Solo decode | 121.29 / 136.93 | 119.05 / 132.07 | 117.90 / 134.36 |
| Two-client aggregate | 126.85 / 138.83 | 122.06 / 137.00 | 122.72 / 135.38 |
| Three-client aggregate | 121.44 / 133.15 | 135.95 / 144.44 | 135.15 / 142.95 |
| Four-client aggregate | 129.98 / 139.01 | 127.90 / 137.92 | 141.13 / 148.74 |

Three slots improved three-client aggregate 11.9%/8.5%, but solo fell 1.8%/3.5%,
two-client aggregate 3.8%/1.3%, and four-client aggregate 1.6%/.8%. Each count
had eight scored solos and six scored groups per client load/workload, after
warmups; 512-token outputs, .6/.95/top_k20/min_p0, thinking off.

**Three slots start all three ordinary clients sooner, not faster individually.**
Worst sampled first-token latency with three clients fell 7.97/7.47 → .98/.99 s
narrative/code. Mean completion wall rose 9.42/8.77 → 11.20/10.55 s; worst
completion wall fell 12.69/11.65 → 11.35/10.83 s. With four clients, three slots
postponed the fourth: worst sampled TTFT 11.34/10.60 s versus two slots'
8.54/8.07 s. These are small-sample maxima, not population p95 estimates.

- Both two-slot arms completed 103/103 expected inference requests; three-slot
  arms 104/104. Runtime differed only by parallel count; actual serving slots,
  engine UUID order, image and profile were matched. No engine/container restart
  or counter reset in passing arms. All intended simultaneous decode counts
  and accepted batch-MTP proposals were proved.
- Two and three slots passed parking (2154 restored tokens), arithmetic/sorting/
  JSON with slots-1 background streams, cancellation isolation and post-cancel
  arithmetic. One 90K prompt plus a short stream remained effectively flat:
  short TTFT about 6.44 s, completion about 15.9 s, long completion about 42.7 s.
- Four long/long/short repetitions per passing count returned correct answers.
  Short completions ranged 52.42–78.52 s with two slots and 27.22–78.68 s with
  three. More slots did not reliably solve serialized prompt-admission waits.
- Both four-slot boots completed the short throughput tests, then the engine
  exited code 1 during 90K ingestion: `prefill gemm: cublasGemmEx: cuBLAS status 14`.
  The short stream returned no content. Later correctness/cancellation checks
  did not run. CUDA-graph eviction appeared 16/36 times versus zero at two/three
  slots. VRAM/graph pressure is a diagnostic lead, not a proved OOM/root cause.
  Four-client speed gains do not override the failures. No reserve/cache tweak
  was made to attempt a fix.
- Primary cache fell 7589 → 7051 → 6522 experts, 14740 → 13699 → 12667 MiB.
  Startup free VRAM stayed about 450 MiB. The third slot removes 1041 MiB of
  primary cache; the fourth another 1032 MiB. The low-headroom warning remains.
- Physical GPU0/1 core peaks were 81/81 C; available RAM floor 43.56 GiB. One
  software thermal-slowdown sample occurred in the first four-slot arm, none
  in the continuation. Caps stayed fixed; no safety guard triggered.

The saved two-slot config was restored unchanged; both .41 services healthy,
authenticated arithmetic, runtime/GPU order and cap readback passed. Five unit
tests, real Compose validation and diff whitespace checks passed. Source/image,
key, models, volume and binding unchanged. No candidate count adopted.

Limits: two boots/count, interrupted ordering, small synthetic samples, no full
agent/thinking-on quality, 240K concurrent ingestion or hour-scale per-count soak.
Three slots merit an operator choice for regular three-client responsiveness.
Four require separate failure/headroom investigation first.

### v0.1.41 promotion (2026-10-08)

The operator approved promotion after the release screen below. The source pin
is `fb58e0dbc8399662c0e47c76578c6e878b14f6cf`; both services use
`strata-local:0.1.41`, tagged from the exact tested image, not rebuilt. CUDA 13,
sm_86 and vision-off build settings stayed fixed. The old .40.3 image and private
rollback files were retained. (E16)

- Both services healthy; engine .41, two serving slots, native 262144 context.
- Runtime JSON exactly matches the .40.3 screen baseline. Models, MTP tensors,
  profile, key, volume, authenticated binding, UUID roles and caps unchanged.
- Engine-process CUDA UUID order and primary 300 W / peer 350 W readback passed.
  Power-policy was recreated on the shared image with the same policy.
- Unauthenticated API returned 401; authenticated arithmetic and metrics passed.
- A live two-client pair produced 512 tokens each. Batch-MTP accepted proposals:
  peak 3.62 emitted rows/window with two slots.
- A → B → A restored 2153 prompt tokens and the expected verification word.
- Primary cache remains 7589 slots / 14740 MiB; startup free VRAM 445 MiB.
  The low-headroom warning remains. No safety abort or OOM during promotion.
- Five deployment tests, real Compose validation, diff whitespace and credential
  checks passed. The build/server suite and long-context screen were reused,
  not rerun during promotion. No new tuning switches were enabled.

Promotion smoke checks do not extend the release screen's quality, fairness or
soak coverage. Stall recovery and forced cache-budget eviction remain untested.

### v0.1.41 peer-mode release screen (2026-10-08)

**The candidate passed; .40.3 was restored at the end of this screen.** The later
operator-approved promotion is above. v0.1.41 was built from
`fb58e0dbc8399662c0e47c76578c6e878b14f6cf` in a separate worktree. Four fresh
boots used .40.3 → .41 → .41 → .40.3, with identical runtime JSON, expert-profile
hash, peer topology, parallel=2, batch-MTP and caps. No experimental switches
were enabled. Test traffic used authenticated loopback with normal API traffic
excluded. Power-policy stayed running. (E15)

| Metric | v0.1.40.3 | v0.1.41 | Change |
| --- | ---: | ---: | ---: |
| Solo narrative decode, tok/s | 119.70 | 119.79 | +0.1% |
| Solo code decode, tok/s | 135.19 | 133.64 | -1.1% |
| Two-client narrative aggregate, tok/s | 124.34 | 124.11 | -0.2% |
| Two-client code aggregate, tok/s | 136.53 | 138.01 | +1.1% |
| Cold 90K prefill, tok/s | 2567.60 | 2560.95 | -0.3% |
| Cold 240K prefill, tok/s | 2287.55 | 2283.15 | -0.2% |

There is no demonstrated material speed gain. Each workload/version had eight
scored solo streams and six scored pairs, after warmups; 512-token output caps,
.6/.95/top_k20/min_p0, thinking off. Within-boot pair CV ranged 1.09–7.87%
narrative and .34–2.29% code. Boot variability exceeds several version deltas.
Mixed 90K/short first-token latency stayed 6.25–6.27 s; long completion stayed
42.38–42.57 s. Do not combine this screen with earlier serial benchmarks.

- Candidate CUDA 13 / sm_86 text-only build passed. Its image server suite ran
  593 tests, 11 skipped, no failures; no GPU, models, secrets or network.
- Runtime equality, engine-process UUID order, authentication and cap readback
  passed. Baseline arms completed 48/48 expected requests, candidates 54/54;
  no counter reset or unexpected container/engine restart occurred.
- Batch-MTP accepted proposals on both candidate boots: peak emitted rows per
  window 3.57/3.51 with two slots. Both slots decoded simultaneously.
- Parking restored 2152 tokens and the expected word. Background arithmetic,
  sorting, JSON and client-disconnect isolation passed. Named tool calls
  (not executed), Responses and low-thinking arithmetic smoke checks passed.
- All eight cold 90K/240K recalls and eight immediate replays passed. Document
  hashes and prompt lengths matched; cold cache_n=0. Actual lengths were
  90058/240061. Replays generated only 12–13 tokens, not long output workloads.
- Candidate long/long/short passed four repetitions, each with three requests
  in flight and control waiters observed. Short completions took 6.03–76.93 s.
  No deadlock in these runs does not establish fairness or low three-client
  latency. The known deadlock sequence was not deliberately run on .40.3.
- Primary cache stayed 7589 slots / 14740 MiB; startup free VRAM stayed 445 MiB.
  Physical GPU0/1 core peaks including transitions were 80/81 C; minimum
  available RAM 46.33 GiB. No OOM or safety abort; caps stayed fixed.
- One software thermal-slowdown sample occurred in the first baseline arm,
  another during production restoration. None occurred in candidate arms.
  The run is not a thermal-limiting-free stress pass.

The first attempt was excluded after a harness assertion used serial `queued`
instead of parallel-engine `waiting`. Its requests returned correctly and
production was restored. The corrected four-arm run above completed in full.
Production was restored again: both .40.3 services healthy, runtime unchanged,
GPU order confirmed and authenticated arithmetic passed. Five deployment tests,
real Compose validation and diff whitespace checks passed.

Limits: two boots/version, fixed ABBA order, small samples, no full agent or
thinking-on quality suite, 240K concurrent ingestion, randomized comparison or
hour-scale soak. Stall recovery and forced full-cache RAM eviction were not
injected. v0.1.41 is a reliability upgrade candidate, not a demonstrated speed
upgrade. This screen did not promote the candidate; source and saved settings
were unchanged until the later approved promotion.

### Peer-mode batch-MTP trial (2026-10-08)

The operator asked to try batch-MTP after the two-slot peer trial. Only
`--batch-mtp` was added; parallel=2, topology, caps, reserve, KV and parking
stayed fixed. After the throughput gain and successful smoke checks, the
operator accepted parallel=2 plus batch-MTP as the new baseline. Acceptance
does not remove the validation limits below. Upstream documents single-GPU support; this screen
establishes limited compatibility on this rig, not general peer support. (E14)

| Metric | Plain two-slot batch | Batch-MTP two-slot |
| --- | ---: | ---: |
| Narrative aggregate, tok/s | 108.86 | 129.51 |
| Code aggregate, tok/s | 109.61 | 138.21 |
| Narrative per-stream decode, tok/s | 56.84 | 68.69 |
| Code per-stream decode, tok/s | 57.38 | 73.49 |
| Solo narrative decode, tok/s | 121.35 | 119.44 |
| Solo code decode, tok/s | 136.09 | 132.63 |
| Later stream first token, narrative, median s | 0.54 | 0.58 |
| Later stream first token, code, median s | 0.62 | 0.55 |

Aggregate improved 19.0%/26.1%; every scored MTP pair exceeded every scored
plain pair. Pair aggregate CV was 0.73/0.75% narrative and 0.89/1.21% code.
Solo observations fell 1.6%/2.5%, small relative to within-arm CV of 2.47/3.81%
and 3.26/5.39%; this is not a firm causal penalty estimate. First-token latency
was effectively similar. Do not combine these figures with older serial runs
to claim a direct matched comparison against serial execution.

Each arm was a fresh boot on .40.3, plain then MTP, with four scored solo streams
and three scored two-client pairs per shape after warmups. Prompts match E13,
with 512-token output caps and .6/.95/top_k20/min_p0 sampling, thinking off.
Runtime JSON differs only by the appended flag. Plain/MTP arms completed
33/33 and 41/41 expected requests on authenticated loopback, with normal API
traffic excluded; no restart or counter reset occurred within an arm.

Activation was proved by >2 emitted rows/window with two slots (up to 3.60 in
the activation check), requiring accepted MTP proposals, not just a requested
flag. Both slots were observed decoding simultaneously. Cache switching restored
2152 tokens and the expected word. Arithmetic, sorting and JSON checks passed
beside a background stream. Disconnecting one client did not stop or contaminate
the survivor; slots returned idle and a subsequent arithmetic request passed.

With 90K ingestion, short first-token latency was 6.16/6.21 s, short completion
19.28/15.50 s, and long completion 43.93/42.26 s. Both recall checks passed;
both resumed from 16384 tokens after yielding. These are one long/short sample
per setting, not broad long-context performance evidence.

Primary cache changed 7648 → 7589 slots, 14854 → 14740 MiB. Initial engine free
VRAM changed 463 → 445 MiB; the low-headroom warning remains. Core peaks on
physical GPU0/1 were plain 64/75 C and MTP 72/77 C; minimum available RAM
57.70/56.38 GiB. No sampled inference thermal flags, cap changes, OOM, safety
abort or unexpected test-container restart occurred.

The tested candidate was saved and deployed from this repo on the existing
authenticated LAN endpoint. Production runtime matched the candidate; a live
pair again proved accepted MTP proposals, and an arithmetic completion passed.
Both services are healthy. Five unit tests, Compose validation, diff/credential
checks and power-cap readback passed. Source/image, key and volume are unchanged.

Limits: one boot/setting, fixed order, small samples, no ABBA/randomized repeat,
240K concurrency, four-client fairness, full thinking-on/tool/Responses agent
quality suite or hour-scale soak. The default batch-MTP gate excludes layer
splits/helpers; do not carry this opt-in into a layer-split experiment.
To revert only this flag, remove --batch-mtp, update saved-setting tests, and
recreate only strata; retain parallel=2 and all other settings/caps.

### Peer-mode parallel=2 trial (2026-10-08)

The operator asked to try two active slots for concurrent projects while keeping
multi-GPU performance in view. At this stage the config gained `"parallel": 2`.
All existing arguments, GPU roles/caps, peer reserve and parking remained fixed.
Batch-MTP was off; the later opt-in trial is above. Plain batching bought
responsiveness at a throughput cost. (E13)

| Metric | Serial | Parallel 2 |
| --- | ---: | ---: |
| Solo narrative decode, tok/s | 123.40 | 121.51 |
| Solo code decode, tok/s | 138.33 | 136.46 |
| Two-client narrative aggregate, tok/s | 115.16 | 107.25 |
| Two-client code aggregate, tok/s | 130.92 | 109.58 |
| Later stream first token, narrative, median s | 4.67 | 0.53 |
| Later stream first token, code, median s | 4.11 | 0.55 |

Solo speed fell 1.5%/1.3%; two-client aggregate fell 6.9%/16.3%. Concurrent
streams averaged about 56–57 tok/s each. These extended essay/code prompts had
512-token output caps and differ from the historical release baseline. Each
setting had four scored solo samples and three scored pairs per shape, after
warmups. Temperature .6/.95/top_k20/min_p0, thinking off.

A separate fresh matched-arrival 90K/short-request test submitted the short
request 0.76/0.75 s after starting ingestion. Short first-token latency improved
34.76 → 6.16 s; completion improved 36.86 → 19.39 s. The long request slowed
34.11 → 43.75 s. Both recall answers passed. The parallel prompt yielded at
16384 tokens; cache_n counts its internal resumed prefix, not a warm document.

- Status and metrics report two slots; both were observed decoding simultaneously.
- Arithmetic, sorting and JSON checks passed beside a live background stream.
- A → B → A restored 2152 prompt tokens and the expected verification word.
- Disconnecting one stream did not stop or contaminate the survivor; slots
  returned idle and a subsequent arithmetic request passed.
- Slot sessions cost 0.95 GiB each / 1.90 GiB total on CUDA0. Primary expert
  cache fell 8647 → 7648 slots, 16814 → 14854 MiB. Initial engine free VRAM
  stayed about 459/463 MiB; the low-headroom warning remains.
- Retained serial/parallel inference core peaks were physical GPU0/1 61/74 C
  and 69/76 C; minimum available RAM 64.15/56.82 GiB. No inference thermal
  flags, OOM, safety abort or unexpected test-container restart.

The serial arm completed 33/33 requests; the parallel retry completed 41/41.
An earlier parallel arm stopped on an invalid harness assertion that a yielded
prompt's cache_n must be zero. Its recall answer was correct; that arm was
excluded. Serial production was restored between attempts. The initial mixed
arrival check also used the wrong metrics field; only the matched recheck above
is compared. All isolated tests used authenticated loopback with normal API
traffic excluded.

The saved config matches the tested candidate. Production was recreated from
this repo and verified with two client streams, status/metrics and an arithmetic
completion. Both services are healthy on the existing authenticated LAN binding.
No test override remained active. At this stage, unit tests verified parallel
propagation and absence of batch-MTP; Compose and diff checks passed.

Limits: one retained throughput boot/setting, interrupted ordering, small sample
counts, no randomized comparison, 240K concurrency, four-client fairness,
batch tool-call/agent suite or hour-scale soak. This screen does not establish
scalable multi-GPU throughput or byte-identical solo/batch answers.
For a current serial rollback, remove both the top-level parallel field and
--batch-mtp, update saved-setting tests, and recreate only strata. Leave
power-policy and all caps unchanged.

### v0.1.40.3 upgrade checks (2026-10-07)

The exact source pin is `d5ea7133741e67743c0e886bb426c0ce8d69cf6c`. Both services
were upgraded from this repo, retaining the old image and private rollback
files. Runtime JSON exactly matched its pre-upgrade snapshot. State, models,
key, authenticated LAN binding, GPU roles and caps were retained. (E11)

- Local CUDA 13.0 / sm_86 build passed, vision disabled.
- Deployment unit tests: 5 passed. Image server suite: 563 tests ran,
  11 skipped, no failures; no GPU or model/secret mounts, external network off.
- Real Compose validation and diff whitespace checks passed.
- Health and authenticated metrics passed. Unauthenticated API returned 401.
- Arithmetic, sorting, JSON and named tool-call smoke checks passed; the tool
  call was inspected, not executed.
- A → B → A restored 2153 of 2160 prompt tokens with the same answer.
- Cold 90K/240K recall passed with archived user-prompt hashes and cache_n=0.
  Actual prompt counts: 90057/240060. Single observed prefill rates:
  2680.4/2338.2 tok/s; not a matched performance comparison.
- Actual engine-process UUID order matched the runtime config: logical CUDA0
  primary at 300 W, CUDA1 peer at 350 W. Cap readback matched.
- Core peaks: physical GPU0/1 63/74 C. Minimum available RAM 56.38 GiB.
  No safety abort or OOM. Thermal slowdown flags were not sampled.

These upgrade smoke checks did not include broad quality, performance A/B,
concurrency, shared-prefix branching or hour-scale soak. The separate baseline
A/B follows below. Initial engine free VRAM was 459 MiB; the low-headroom warning
remains.

### Matched v0.1.40.1/v0.1.40.3 A/B (2026-10-07)

Two fresh boots per version used identical runtime JSON, expert-profile hash,
parking, serial serving and GPU caps. All arms ran on authenticated loopback
port 8081 with the normal API offline; each had exactly 52/52 expected requests.
Balanced order: A(.40.1) → B(.40.3) → B(.40.3) → A(.40.1). Nothing was reused
from the historical A/B. (E12)

| Metric | v0.1.40.1 mean | v0.1.40.3 mean | Change |
| --- | ---: | ---: | ---: |
| Narrative decode, tok/s | 115.09 | 117.30 | +1.9% |
| Code decode, tok/s | 147.46 | 152.87 | +3.7% |
| Cold 90K prefill, tok/s | 2580.40 | 2574.10 | -0.2% |
| Cold 240K prefill, tok/s | 2292.10 | 2287.45 | -0.2% |
| Cached 90K tail replay, ms | 4867.40 | 4846.25 | -0.4% |
| Cached 240K tail replay, ms | 8552.10 | 8552.00 | approximately 0% |
| Cached 90K request wall, s | 10.627 | 10.681 | +0.5% |
| Cached 240K request wall, s | 14.750 | 14.680 | -0.5% |

Each boot had a full unscored pass, then two scored passes with three warmups
and five measurements per shape/pass: 20 scored samples per shape/version.
Canonical sampling was .6/.95/top_k20/min_p0, thinking off. Long tests used the
same archived prompts, greedy, with matching token counts and cache_n. All eight
recall checks passed; all eight cached generations produced 512 tokens.

Both paired decode comparisons improved: narrative +1.0%/+2.9%, code
+3.8%/+3.6%. Within-boot CV was 1.21–2.32% narrative and 2.42–3.32% code.
The observed gains are modest; the narrative effect is small relative to run
variation. Cold prefill, replay and long-request wall times were effectively
flat. Cached generation-only decode changed -1.6% at 90K and +0.7% at 240K;
there was no consistent long-context speedup. No upstream optimization was
isolated, and these are retained builds rather than identical dependency layers.

Core peaks were physical GPU0/1 80/81 C; minimum available RAM was 59.21 GiB.
No OOM, safety abort or test-container restart occurred. One software-thermal
flag appeared during B1 startup before readiness, with primary GPU memory at
1 MiB. No thermal-active samples occurred during benchmark inference. Caps
remained 350/300 W. The primary cache stayed at 8647 slots; initial free VRAM
was 463 MiB on .40.1 and 459 MiB on .40.3.

The normal authenticated .40.3 deployment was restored from this repo, with
both services healthy and a completion verified. Unit tests, Compose validation,
diff whitespace and credential scans passed. The server suite was already run
at upgrade; it was not rerun alongside timing measurements.

Limits: two boots/version, not randomized or hour-scale heat-soaked; sampled
outputs vary. Sparse long samples do not establish broad reasoning quality.
That baseline A/B did not test full quality/thinking-on, agent workflows or
concurrency. Do not combine the historical .39/.40.1 gain with this run to
claim a direct .39/.40.3 comparison.

### v0.1.40.1 build and static checks

- Local Docker build completed with CUDA 13.0, sm_86, and vision disabled.
- Deployment unit tests: 5 passed.
- Upstream server suite inside the new image, without GPU access or model/secret
  mounts: 452 tests ran, 10 skipped, no failures.
- Initial Compose validation passed with placeholder UUIDs and paths before
  migration. Real host configuration passed validation after `.env` was created.
- Diff whitespace check passed. No engine settings or power-policy code changed.

These build/static checks alone do not prove live inference or performance.

### v0.1.40.1 migration smoke checks (2026-10-06)

The original deployment migrated to this repo's Compose file. The existing
state volume, API key, authenticated LAN binding, UUID ordering, and power caps
were retained. Model paths changed only inside the container; engine arguments
were checked for equality after path translation.

- Both services healthy; engine 0.1.40, native 262144 context, vision disabled.
- Unauthenticated API request refused with 401; authenticated completion passed.
- Authenticated metrics confirmed parking enabled, 16384 MiB budget, 8 slots.
- A → B → A returned the expected deterministic answers and restored 2153 of
  2160 prompt tokens on the final A.
- Runtime UUID ordering maps the 300 W primary to logical CUDA0 and the 350 W
  peer to CUDA1. Cap readback matched. Runtime JSON contains no API key.
- Startup confirmed peer prompt offload with 2346 MiB free on the peer.

This is a smoke test, not a full quality, long-context, performance, sustained
multi-client, or thermal validation. No new tuning opt-ins were enabled.

### v0.1.40.1 upgrade screen (2026-10-06)

Current production was screened without restarts or settings changes. The
comparison is against recorded v0.1.39 results, not a controlled A/B. (E9)

| Metric | Historical v0.1.39 | Current v0.1.40.1 |
| --- | ---: | ---: |
| Narrative decode tok/s | 108.17 | 116.25 |
| Code decode tok/s | 139.55 | 150.54 |
| Cold 90K prefill tok/s | 2591.4 | 2606.8 |
| Cold 240K prefill tok/s | 2308.1 | 2302.3 |
| Cached 90K generation wall s | 9.996 | 10.727 |
| Cached 240K generation wall s | 12.997 | 14.677 |
| Thinking-off quality, first attempt | 64/75 | 64/75 |

Decode measured about 7.5%/7.9% faster over ten scored samples per workload;
CV was 1.91%/2.59%. One full warmup pass preceded two scored passes. Cold long
prefill changed by less than 1%. Both 90K/240K recall checks passed with identical
historical prompt hashes. Quality pack versions, raw scenarios and runner
version matched; no first-attempt pass/fail flips. Current retries allowed two
total attempts versus three historically; retry scores are not compared.

**Long cached requests were slower despite faster decode.** Replay took
4819.6/8463.7 ms versus 3770.4/6247.0 ms at 90K/240K. Total generation request
walls rose 7.3%/12.9%. These are single samples. Historical parking was disabled;
current parking remains enabled. Different sessions, boots, thermal conditions
and a new authenticated measurement script also limit attribution. The matched
A/B below reproduced the decode gain, not the cached-tail slowdown.

GPU0/1 core peaks were 79/78 C, with no sampled thermal slowdown flags. Available
host RAM reached 54.73 GiB; host-wide swap used at most 0.50 MiB. No OOM, safety
abort or container restart. Initial engine free VRAM was 463 MiB: the upgrade
does not resolve the low-headroom warning. No full sandbox, thinking-on,
multi-client, or hour-scale heat-soak tests were run.

### Matched v0.1.39/v0.1.40.1 A/B (2026-10-06)

Two fresh boots per version used identical runtime JSON, parking settings,
profile hash, model artifacts, GPU roles, and caps. Each boot had one full
unscored warmup pass and two scored passes: twenty scored samples per workload
per version. Clean scored order was A → B → A → B. (E10)

| Metric | v0.1.39 mean | v0.1.40.1 mean | Change |
| --- | ---: | ---: | ---: |
| Narrative decode tok/s | 108.38 | 115.98 | +7.0% |
| Code decode tok/s | 140.88 | 148.37 | +5.3% |
| Cold 90K prefill tok/s | 2578.7 | 2573.9 | -0.2% |
| Cold 240K prefill tok/s | 2291.8 | 2292.7 | +0.04% |
| Cached 90K tail replay ms | 4845.2 | 4853.6 | +0.2% time |
| Cached 240K tail replay ms | 8482.0 | 8465.9 | -0.2% time |
| Cached 90K generation wall s | 11.051 | 10.821 | -2.1% time |
| Cached 240K generation wall s | 15.005 | 14.566 | -2.9% time |

Both pairs improved canonical decode: narrative +7.6%/+6.4%, code +5.6%/+5.0%.
All eight long recall checks passed, with matching prompt hashes, token counts
and prefix reuse. Cold prefill and tail replay were effectively unchanged.
The historical replay slowdown did not reproduce with a fresh parking-matched
baseline; its cause was not isolated. Long generation is a sparse sample: two
512-token requests per depth per version, not a broad context-quality test.

An initial .40.1 arm received an unrelated request and was discarded. Its
uncontaminated .39 baseline was retained; the remaining arms used an
authenticated loopback-only test port. All clean arms had exactly 52 expected
requests. An interruption/restoration separates the retained baseline from the
remaining arms. This is not randomized or uninterrupted ABAB, nor an hour-scale
per-arm heat soak. No fresh quality suite was run in the A/B.

Combined GPU0/1 core peaks were 79/80 C, with no sampled thermal slowdown flags.
Minimum available RAM was 59.26 GiB; host swap used at most 0.50 MiB. No safety
abort, OOM, unexpected restart, or changed caps in clean arms. Production was
restored to .40.1 on the normal authenticated endpoint, managed from this repo.
No test override or test port remains active. Engine settings are unchanged.

## Operational limits

The v0.1.38 full suite completed long-context requests without OOM, but failed
its generic 1 GiB free-VRAM guard: the primary had only 294 MiB free in the
reported accounting. Automatic expert-cache filling leaves little margin.
Do not co-host another GPU workload or call this a clean stress-gate pass. (E7)

The full 150-case suite applies to v0.1.38, not v0.1.39, v0.1.40.1, v0.1.40.3
or v0.1.41. The v0.1.39 upgrade screen did not repeat thinking-on or
parallel-serving tests.
The v0.1.40.1 smoke, quality-screen, and matched A/B checks do not replace those
suites. The .40.3 upgrade checks and .41 release/promotion screens are smaller
in scope. Clean-machine, broad quality, long-context reasoning, agent workflows,
broader multi-client and
sustained-load tests for the current pin remain open.

Authentication, loopback binding, read-only model mounts, and the isolated
power-policy service are deployment safeguards, not performance tuning. See
[README.md](README.md#security-and-operations) for operation and recovery.

## Evidence records

E1–E8 live under `/opt/ai/Strata/bench/results/` on the original rig. E9–E10 and
E12–E15 and E17–E18 live under `/opt/ai/Strata-backups/evaluations/`; E11 and E16 are under
`/opt/ai/Strata-backups/`. They are not included in this repo. The summaries
above omit private GPU UUIDs and LAN addresses. Earlier tests used v0.1.38 unless marked otherwise.

| ID | Record | Relevant evidence |
| --- | --- | --- |
| E1 | `20261003-092909-iq3_s-gpu-comparison/README.md` | Peer reserve, prompt buffers, split/peer tradeoffs |
| E2 | `20261003-150709-peer-reversal-256k/README.md` | GPU reversal, caps, thermals, recall |
| E3 | `20261003-140911-gpu-power-sweep-256k/README.md` | 350/300/280 W screening and heat-soak limits |
| E4 | `20261003-094704-iq3_s-256k-context/README.md` | Native long-input feasibility and positional recall |
| E5 | `20261003-121649-iq3_s-calibration-256k/README.md`; `20261003-123459-calibration-validation-256k/README.md` | Calibration proposals and saved-baseline validation |
| E6 | `20261003-161045-kv-resident-256k/README.md` | Residency sweep and expert-cache displacement |
| E7 | `20261003-190622-production-full-suite/ANALYSIS.md` | Longer mixed evaluation, thermals, free-VRAM warning |
| E8 | `20261004-092723-v039-upgrade-validation/ANALYSIS.md` | v0.1.39 performance, quality screen, and test gaps |
| E9 | `20261006-091747-v0401-screen/ANALYSIS.md` | v0.1.40.1 live screen versus historical v0.1.39; decode, replay, recall, quality and telemetry |
| E10 | `20261006-095827-v039-v0401-matched-ab-isolated/ANALYSIS.md` | Fresh matched two-boot A/B; decode gains, unchanged replay, recall, telemetry and restoration |
| E11 | `upgrade-v0403-20261007-212242/ANALYSIS.md` | v0.1.40.3 build/server tests, rollout, functional/cache/long-recall checks and rollback records |
| E12 | `20261007-214322-v0401-v0403-matched-ab/ANALYSIS.md` | Fresh matched ABBA baseline; modest decode gains, flat prefill/replay, recall, telemetry and .40.3 restoration |
| E13 | `20261008-094412-parallel2-peer-validated/ANALYSIS.md` | Two-slot peer trial; latency/throughput tradeoff, overlap, cache, cancellation, matched-arrival recheck and live activation |
| E14 | `20261008-101518-batch-mtp-peer-trial/ANALYSIS.md` | Two-slot peer batch-MTP; activation, throughput gains, overlap, cache, cancellation, memory and live adoption |
| E15 | `20261008-110356-v041-peer-matched/ANALYSIS.md` | Four-boot .40.3/.41 peer batch-MTP screen; flat speed, activation, cache, recall, concurrency and .40.3 restoration. Build/server tests linked in `build-evidence-path.txt`. |
| E16 | `20261008-114153-promote-v041/ANALYSIS.md` | Approved .41 promotion of tested image; runtime equality, authentication, UUID/cap checks, two-client MTP activation and cache switching. |
| E17 | `20261008-122331-peer-slot-sweep-continued/ANALYSIS.md` | Two boots each at 2/3/4 slots; three-client latency/throughput tradeoff, repeated four-slot cuBLAS failures and two-slot restoration. First half linked by `first-attempt-path.txt`. |
| E18 | `20261008-131908-peer-prefill-sweep-captured/ANALYSIS.md` | Matched auto/4096/2048 chunks; short TTFT gains, cold-ingestion losses, peer thermal limiting, correctness and auto restoration. Excluded first attempt linked in `excluded-attempt-path.txt`. |

The operator supplied the model, KV precision, vision, parking, and thermal
rationales. The operator confirmed MTP4 was inherited. Automatic cache/prefill
remain saved settings without a documented local selection rationale.
