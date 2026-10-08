# strata-local

Local-build Docker deployment for Strata on Linux with 128 GB RAM and two NVLink
RTX 3090s. No published container images. This repo contains configuration,
startup scripts, and a pinned source submodule. Store models and secrets separately.

## Saved configuration

See [SETTINGS.md](SETTINGS.md) for the rationale, test evidence, and tuning limits.

- Strata v0.1.41: `fb58e0dbc8399662c0e47c76578c6e878b14f6cf`,
  from [Niko1221/Strata](https://github.com/Niko1221/Strata).
- CUDA 13.0; sm_86 build; vision disabled.
- Original rig: physical GPU1 primary at 300 W; physical GPU0 peer at 350 W.
  Set UUIDs explicitly. Primary becomes logical CUDA0; peer becomes logical CUDA1.
- IQ3_S; native 262144-token context; INT8 KV; 32768 resident KV tokens.
- Automatic expert cache/prefill; MTP4; PCIe fraction .20; draft confidence .70.
- Peer reserve 3072 MiB; normal prompt checkpoints enabled.
- Conversation parking: 16384 MiB host-RAM budget; up to 8 parked conversations.
  The budget is a ceiling, not an upfront allocation.
- Accepted concurrency baseline: `parallel: 2` in peer mode, with `--batch-mtp`.
  Batch-MTP improved two-client aggregate throughput 19% narrative / 26% code
  over plain batching in a small peer-mode screen; broad validation remains open.
- Authentication required, including on the default loopback binding.

Original engine settings are retained except for the accepted two-slot
concurrency and batch-MTP baseline. The source pin is v0.1.41; build, server tests,
authenticated checks, cache switching and 90K/240K recall passed. Both services
use the locally built v0.1.41 image; the engine reports 0.1.41. A fresh four-boot
comparison against v0.1.40.3 found no material speed gain with the current peer
settings. Four long/long/short repetitions completed without deadlock, but short
requests sometimes waited up to 77 s. The operator approved promotion for
reliability, not speed; settings and caps stayed unchanged.
Plain two-slot batching improved responsiveness but cost aggregate throughput.
The subsequent batch-MTP trial recovered speed; these are separate comparisons.
Full quality, broader concurrency and sustained-load validation remain pending.
See SETTINGS.md for the version-specific results and limits. Builds are not
guaranteed bit-for-bit identical: the upstream Dockerfile uses a tagged CUDA
base and mutable dependencies. Native CPU build defaults require a rebuild on
the destination rig.

## Restore after a wipe

### 1. Install prerequisites and clone

Install Git, Docker Engine with Compose v2, an NVIDIA driver for CUDA 13.0
(upstream recommends >=580), and NVIDIA Container Toolkit configured for Docker.
Verify host `nvidia-smi`. Reserve disk space for CUDA build layers, approximately
70–120 GB of model artifacts, and backups. Read the pinned source's
`docs/AI_SETUP.md`.

```sh
git clone --recurse-submodules https://github.com/TreyThomasCodes/strata-local.git
cd strata-local
cp .env.example .env
nvidia-smi --query-gpu=index,uuid,power.limit --format=csv
```

Edit `.env`. Replace both GPU placeholders with UUIDs. Set absolute data and
API-key paths. Hardware replacement can change GPU indices and UUIDs. Use power
limits supported by the destination cards. This configuration targets two 3090s;
it does not size hardware automatically.

### 2. Restore models and key

Restore your separate `Strata-data` backup to `STRATA_DATA_DIR`:

```text
packs/iq3_s/              # prepared expert pack, including tokenizer/
models/IQ3_S/
  Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf
  Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf
mtp/rt/                  # prepared speculative draft tensors
```

The prepared pack is a directory, not only the GGUFs. Back up all artifacts for
fast recovery. This repo contains none; startup neither downloads nor regenerates
missing files. Keep a checksum manifest with the backup. Verify restored artifacts.

Without an artifact backup, use the pinned source installer to download and
prepare IQ3_S. Read `vendor/Strata/docs/AI_SETUP.md`. Start with this command for
the Linux rig:

```sh
(cd vendor/Strata && ./setup.sh --yes --family qwen --model IQ3_S \
  --vision no --context 262144 --data-dir /opt/ai/Strata-data --no-start)
```

The installer can also build native tools and generate settings. This deployment
uses `config/strata-iq3_s.json`, not the generated run configuration. Match the
data directory to `.env`. Verify the layout above.

Restore the API key from a password manager or encrypted backup. To rotate it,
create a new key and update clients. Create a key at the default path:

```sh
install -d -m 700 /opt/ai/Strata-secrets
(umask 077; openssl rand -hex 32 > /opt/ai/Strata-secrets/api-key)
```

Do not overwrite a restored key unless rotating it. Keep keys out of this repo,
images, command-line arguments, and shared logs.

### 3. Build and start

```sh
docker compose config --quiet
docker compose build strata
docker compose up -d --no-build
docker compose ps
docker compose logs --tail=100 strata power-policy
curl -fsS http://127.0.0.1:8080/health
```

Both services use one locally built image. Builds download CUDA base layers and
compiler/Python dependencies, then compile Strata locally. No Strata image
registry dependency. Stop the old deployment before migrating: two model servers
must not share these cards or the host port.

Verify health reports `loaded: true`, `max_context: 262144`, and `api_key: true`.
Test an authenticated completion and `/metrics`. Confirm engine version 0.1.41,
conversation cache enabled, budget 16384 MiB, and 8 parked slots. Confirm
`/v1/status` reports `concurrency.serving: 2`; active and parked slots differ.
Use API base URL `http://127.0.0.1:8080/v1` and model
`qwen3.8-flash-next-iq3_s`.
Check UUID-bound power caps with `nvidia-smi`.

## Security and operations

Configuration is public. Git excludes `.env`, secrets, models, runtime logs, and
backups. The example contains no real GPU UUIDs or LAN IP. Review staged files
before every push. `.gitignore` does not scan for secrets.

The default host binding is `127.0.0.1`. Set `STRATA_BIND_HOST=0.0.0.0` for a
trusted LAN. The entrypoint rejects empty API keys. Use TLS or a secure tunnel on
untrusted networks. Never forward the HTTP port publicly. Metrics require
authentication; `/health` is public.

Only the utility-only power-policy service has SYS_ADMIN. It has no network,
model mounts, or secret mounts. It checks caps every 30 seconds and repairs
resets. Stopping it leaves the current limits in place. Stop it before manual
power experiments. The server has no SYS_ADMIN.

```sh
docker compose stop                  # stop both services
docker compose up -d --no-build       # restart
docker compose down                  # retain named state volume and model files
```

Avoid routine `down -v`: it deletes the state volume. The `strata-state` volume
holds runtime config and logs; neither is required to rebuild. Conversation
parking is memory-only. Back up the volume separately to retain logs or runtime
settings. Keep this repo and model/key backups off the rig before wiping it.

## Update and validate

Do not run `git submodule update --remote` blindly: it leaves the tested commit.
Upstream rewrote history for v0.1.40.1. Do not apply its `git reset --hard
origin/main` update recipe to this wrapper or its pinned submodule. Fetch and
check out an exact release commit instead.

To upgrade, select a source commit in `vendor/Strata`, build, and test quality,
cache switching, and long-context behavior. Commit the new submodule pointer.

```sh
git submodule update --init --recursive
python3 -m unittest discover -s tests -v
```

Original-rig cache smoke test (2026-10-05): A → B → A restored 1984 of 1991 prompt
tokens and returned the same deterministic answer. The test did not measure
sustained multi-client or long-context cache performance.

On 2026-10-06, the original stack migrated to this wrapper at v0.1.40.1.
Health, authenticated completions, metrics, peer prompt offload, GPU ordering,
and power caps passed live checks. A → B → A restored 2153 of 2160 prompt tokens
with the same deterministic answer. A later screen passed 90K/240K recall
and scored 64/75 thinking-off quality, unchanged from v0.1.39. A fresh matched
two-boot A/B then measured +7.0% narrative and +5.3% code decode. Cold prefill
and cached-tail replay were unchanged; all eight long recall checks passed.
The apparent historical replay slowdown did not reproduce. See
[SETTINGS.md](SETTINGS.md#matched-v0139v01401-ab-2026-10-06) for numbers and limits.
Those results apply to v0.1.40.1. On 2026-10-07, v0.1.40.3 passed build/server
tests, authenticated functional checks, cache switching and 90K/240K recall.
A separate fresh matched A/B against v0.1.40.1 measured +1.9% narrative and
+3.7% code decode with unchanged settings. Cold prefill, cached-tail replay and
long-request wall times were effectively unchanged; eight recall checks passed.
See [SETTINGS.md](SETTINGS.md#matched-v01401v01403-ab-2026-10-07). Full quality,
broader concurrency, sustained-load and clean-machine checks remain pending.

On 2026-10-08, the peer-mode `parallel: 2` trial passed two-client, cache,
long/short overlap, correctness and cancellation smoke checks. Solo speed fell
about 1–2%; aggregate two-client throughput fell 7% narrative / 16% code.
The later stream started in about 0.5–0.6 s rather than 4–5 s. During matched
90K ingestion, the short request's first token improved from 34.8 s to 6.2 s;
the long request took longer. Two slots were retained, with all other settings
fixed at this stage. See [SETTINGS.md](SETTINGS.md#peer-mode-parallel2-trial-2026-10-08).

A later `--batch-mtp` peer trial improved two-client aggregate throughput
108.9 → 129.5 tok/s narrative and 109.6 → 138.2 tok/s code. Activation, cache,
overlap, correctness and cancellation smoke checks passed. Batch-MTP remains
enabled with two slots as the operator-approved baseline. Upstream documents
single-GPU support; this limited
peer test is not broad compatibility or quality validation. See
[SETTINGS.md](SETTINGS.md#peer-mode-batch-mtp-trial-2026-10-08).

On 2026-10-08, v0.1.41 passed a four-boot comparison against .40.3 with the
current peer/two-slot/batch-MTP settings. Speed was effectively flat; activation,
cache, cancellation, tool/Responses smoke, cold and replayed 90K/240K recall,
and four candidate long/long/short repetitions passed. The candidate server
suite ran 593 tests, 11 skipped, no failures. After operator approval, both
services were promoted using the tested image. Health, authenticated completion,
GPU ordering, caps, two-client batch-MTP activation and cache switching passed.
Source and image changed; model, key, volume, binding and engine settings did not.
The .40.3 image remains available for rollback. See
[SETTINGS.md](SETTINGS.md#v0141-promotion-2026-10-08). Full quality and soak testing,
forced cache-budget eviction and stall-recovery injection remain untested.

A later .41 peer-mode slot sweep retained two active slots. Three improved
three-client startup latency and aggregate throughput but cost solo/two-client
speed; they did not reliably fix long/long/short admission delays. Four completed
short throughput tests but failed 90K ingestion on both boots with cuBLAS status
14. Do not adopt four slots as tested. See
[SETTINGS.md](SETTINGS.md#peer-mode-active-slot-sweep-2026-10-08).

The prefill-chunk sweep retained `--prefill auto`. Fixed 4096/2048 reduced short
first-token latency beside 90K ingestion from 7.0 s to 4.2/2.8 s, but cold
long-prompt wall time rose 14–15% / 43–45% and peer thermal limiting appeared in both
fixed-chunk boots per setting. Three-request admission delays remained variable.
See [SETTINGS.md](SETTINGS.md#peer-mode-prefill-chunk-sweep-2026-10-08).

The original rig's ignored `.env` sets `COMPOSE_PROJECT_NAME=strata` to retain
the existing `strata_strata-state` volume and preserves its authenticated LAN
binding. Docker now records this repo's `compose.yaml` as the running stack's
configuration. Run service commands from this repo, not `/opt/ai/Strata`.
The old Compose file is retired; old images remain available for rollback.

## License

This deployment wrapper uses the [MIT License](LICENSE).
Strata retains its [upstream license](vendor/Strata/LICENSE).
Model artifacts have separate licenses; this license does not cover them.
