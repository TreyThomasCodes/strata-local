# strata-local

Local-build Docker deployment for Strata on Linux with 128 GB RAM and two NVLink
RTX 3090s. No published container images. This repo contains configuration,
startup scripts, and a pinned source submodule. Store models and secrets separately.

## Saved configuration

- Strata v0.1.39: `6f32ec070f23ced9f50e704d854d775da52591ab`,
  from [Niko1221/Strata](https://github.com/Niko1221/Strata).
- CUDA 13.0; sm_86 build; vision disabled.
- Original rig: physical GPU1 primary at 300 W; physical GPU0 peer at 350 W.
  Set UUIDs explicitly. Primary becomes logical CUDA0; peer becomes logical CUDA1.
- IQ3_S; native 262144-token context; INT8 KV; 32768 resident KV tokens.
- Automatic expert cache/prefill; MTP4; PCIe fraction .20; draft confidence .70.
- Peer reserve 3072 MiB; normal prompt checkpoints enabled.
- Conversation parking: 16384 MiB host-RAM budget; up to 8 parked conversations.
  Requests execute serially. The budget is a ceiling, not an upfront allocation.
- Authentication required, including on the default loopback binding.

The source commit and settings match the original production deployment. Both
services use the locally built v0.1.39 image; the original power-policy sidecar
used v0.1.38. Builds are not guaranteed bit-for-bit identical: the upstream
Dockerfile uses a tagged CUDA base and mutable dependencies. Native CPU build
defaults require a rebuild on the destination rig.

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
Test an authenticated completion and `/metrics`. Confirm engine version 0.1.39,
conversation cache enabled, budget 16384 MiB, and 8 slots. Use API base URL
`http://127.0.0.1:8080/v1` and model `qwen3.8-flash-next-iq3_s`.
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
To upgrade, select a source commit in `vendor/Strata`, build, and test quality,
cache switching, and long-context behavior. Commit the new submodule pointer.

```sh
git submodule update --init --recursive
python3 -m unittest discover -s tests -v
```

Original-rig cache smoke test (2026-10-05): A → B → A restored 1984 of 1991 prompt
tokens and returned the same deterministic answer. The test did not measure
sustained multi-client or long-context cache performance. This portable Compose
wrapper has static/unit validation only. Verify a clean-machine build and live
deployment. Creating the wrapper does not change the original running stack.
