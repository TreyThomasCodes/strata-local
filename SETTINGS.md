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
operator enabled it for multiple ongoing chats or agent conversations. Requests
still execute one at a time; parking is not parallel inference.

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

**Strata v0.1.40.3 is pinned; build, server tests, live upgrade checks and a
matched two-boot baseline comparison passed.** Engine settings remain unchanged;
concurrency and new opt-ins remain off. The engine reports 0.1.40.3. Full quality,
concurrency and sustained-load validation for this pin remain pending.

The v0.1.40.1 quality-screen and matched two-boot results below remain specific
to that version. The .40.3 upgrade includes default verify-window improvements,
batching and K8V4 fixes, startup/restart safeguards, and MTP router hardening.
Its short correctness checks do not establish performance gains.

**Earlier measurements remain version-specific.** The v0.1.39 screen
measured 108.17/139.55 tok/s narrative/code versus 99.74/129.70 for the combined
v0.1.38 baseline. Cold 240K prefill measured 2308.1 versus 1967.0 tok/s. The
thinking-off quality screen scored 64/75 versus 63/75; one case does not prove
better model quality. All eight long-context recall checks passed. (E8)

CUDA 13.0, sm_86, and native CPU defaults match the tested build. sm_86 targets
the RTX 3090 architecture. No compiler-tuning comparison was recorded. Rebuild
on the destination CPU; the source pin does not freeze base images or packages.

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
Full quality/thinking-on, agent workflows and concurrency remain untested.
Do not combine the historical .39/.40.1 gain with this run to claim a direct
.39/.40.3 comparison.

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

The full 150-case suite applies to v0.1.38, not v0.1.39, v0.1.40.1 or v0.1.40.3. The
v0.1.39 upgrade screen did not repeat thinking-on or parallel-serving tests.
The v0.1.40.1 smoke, quality-screen, and matched A/B checks do not replace those
suites. The .40.3 upgrade checks are smaller in scope. Clean-machine, broad
quality, long-context reasoning, agent workflows, multi-client and
sustained-load tests for the current pin remain open.

Authentication, loopback binding, read-only model mounts, and the isolated
power-policy service are deployment safeguards, not performance tuning. See
[README.md](README.md#security-and-operations) for operation and recovery.

## Evidence records

E1–E8 live under `/opt/ai/Strata/bench/results/` on the original rig. E9–E10 and E12 live
under `/opt/ai/Strata-backups/evaluations/`; E11 is under
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

The operator supplied the model, KV precision, vision, parking, and thermal
rationales. The operator confirmed MTP4 was inherited. Automatic cache/prefill
remain saved settings without a documented local selection rationale.
