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

**Strata v0.1.39 is pinned to preserve the tested source.** The v0.1.39 screen
measured 108.17/139.55 tok/s narrative/code versus 99.74/129.70 for the combined
v0.1.38 baseline. Cold 240K prefill measured 2308.1 versus 1967.0 tok/s. The
thinking-off quality screen scored 64/75 versus 63/75; one case does not prove
better model quality. All eight long-context recall checks passed. (E8)

CUDA 13.0, sm_86, and native CPU defaults match the tested build. sm_86 targets
the RTX 3090 architecture. No compiler-tuning comparison was recorded. Rebuild
on the destination CPU; the source pin does not freeze base images or packages.

## Operational limits

The v0.1.38 full suite completed long-context requests without OOM, but failed
its generic 1 GiB free-VRAM guard: the primary had only 294 MiB free in the
reported accounting. Automatic expert-cache filling leaves little margin.
Do not co-host another GPU workload or call this a clean stress-gate pass. (E7)

The full 150-case suite applies to v0.1.38, not v0.1.39. The upgrade screen did
not repeat thinking-on or parallel-serving tests. This portable wrapper still
needs a clean-machine build and live validation.

Authentication, loopback binding, read-only model mounts, and the isolated
power-policy service are deployment safeguards, not performance tuning. See
[README.md](README.md#security-and-operations) for operation and recovery.

## Evidence records

These records live under `/opt/ai/Strata/bench/results/` on the original rig.
They are not included in this repo. The summaries above omit private GPU UUIDs
and LAN addresses. Earlier tests used v0.1.38 unless marked otherwise.

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

The operator supplied the model, KV precision, vision, parking, and thermal
rationales. The operator confirmed MTP4 was inherited. Automatic cache/prefill
remain saved settings without a documented local selection rationale.
