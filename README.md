# strata-local

Local-build Docker deployment for Strata on a Linux PC with 128 GB RAM and two
NVLink RTX 3090s. No container images are published. This repository holds only
configuration, startup scripts, and a pinned source submodule; model files and
secrets are stored separately.

## Saved configuration

- Strata v0.1.39 source: `6f32ec070f23ced9f50e704d854d775da52591ab`,
  from [Niko1221/Strata](https://github.com/Niko1221/Strata).
- CUDA 13.0; sm_86 build; vision disabled.
- Physical GPU1 was primary at 300 W; physical GPU0 was peer at 350 W.
  Set UUIDs explicitly: primary becomes logical CUDA0, peer becomes logical CUDA1.
- IQ3_S; native 262144-token context; INT8 KV; 32768 resident KV tokens.
- Automatic expert cache/prefill; MTP4; PCIe fraction .20; draft confidence .70.
- Peer reserve 3072 MiB; normal prompt checkpoints enabled.
- Conversation parking: 16384 MiB host-RAM budget, up to 8 parked conversations.
  Requests still execute one at a time. Budget is a ceiling, not an upfront allocation.
- Authentication required, even with the default loopback-only port binding.

The source commit and settings match the original production deployment. This
portable wrapper uses the newly built v0.1.39 image for both services; the original
power-policy sidecar used v0.1.38. Rebuilds are not promised to be bit-for-bit
identical: the upstream Dockerfile uses a tagged CUDA base and installs dependencies
that can change. It uses native CPU build defaults; rebuild on the destination rig.

## Restore after a wipe

### 1. Host prerequisites and source

Install Git, Docker Engine with Compose v2, an NVIDIA driver suitable for CUDA
13.0 (upstream recommends >=580), and NVIDIA Container Toolkit configured for
Docker. Verify `nvidia-smi` works on the host. Allow enough disk space for CUDA
build layers plus approximately 70–120 GB of model artifacts; keep additional
space for backups. Consult the pinned source's `docs/AI_SETUP.md`.

```sh
git clone --recurse-submodules https://github.com/TreyThomasCodes/strata-local.git
cd strata-local
cp .env.example .env
nvidia-smi --query-gpu=index,uuid,power.limit --format=csv
```

Edit `.env`: replace both GPU placeholders with UUIDs and set the absolute data
and API-key paths. GPU indices/UUIDs may differ after hardware replacement.
Power limits must be supported by the destination cards. This is a two-3090
configuration, not an automatic hardware-sizing installer.

### 2. Restore models and key

Restore the contents of your separate `Strata-data` backup to `STRATA_DATA_DIR`:

```text
packs/iq3_s/              # prepared expert pack, including tokenizer/
models/IQ3_S/
  Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf
  Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf
mtp/rt/                  # prepared speculative draft tensors
```

The prepared pack is a directory, not just the GGUFs. Keep all of these artifacts
in a separate backup if fast recovery matters. This repo does not contain them,
and startup does not download or regenerate missing files. Keep a checksum manifest
with your artifact backup to verify it after restoration.

If no artifact backup exists, use the pinned source installer to download/prepare
IQ3_S. Read `vendor/Strata/docs/AI_SETUP.md` first. For this Linux rig, a starting
command is:

```sh
(cd vendor/Strata && ./setup.sh --yes --family qwen --model IQ3_S \
  --vision no --context 262144 --data-dir /opt/ai/Strata-data --no-start)
```

That may also build native tools and generate its own settings. This deployment
uses `config/strata-iq3_s.json`, not the installer-generated run configuration.
Adjust the data directory to your `.env`; verify the expected layout above.

Recover your API key from a password manager/encrypted backup, or create a new
one and update clients. Example to create a new key at the default location:

```sh
install -d -m 700 /opt/ai/Strata-secrets
(umask 077; openssl rand -hex 32 > /opt/ai/Strata-secrets/api-key)
```

Do not overwrite a restored key unless you intend to rotate it. No key belongs
in this repository, an image, a command-line argument, or a shared log.

### 3. Build and start

```sh
docker compose config --quiet
docker compose build strata
docker compose up -d --no-build
docker compose ps
docker compose logs --tail=100 strata power-policy
curl -fsS http://127.0.0.1:8080/health
```

Both services use the same locally built image. Builds download CUDA base layers
and compiler/Python dependencies but compile Strata here. There is no Strata image
registry dependency. Do not run this deployment alongside another model server
using the same cards or host port. Stop the old deployment before migrating.

Health should report `loaded: true`, `max_context: 262144`, and `api_key: true`.
Verify an authenticated completion and `/metrics`: engine version 0.1.39,
conversation cache enabled, budget 16384 MiB, slots 8. API base URL is
`http://127.0.0.1:8080/v1`, model `qwen3.8-flash-next-iq3_s`.
Check UUID-bound power caps with `nvidia-smi`.

## Security and operations

Public configuration is intentional. `.env`, secrets, model files, runtime logs,
and backups are excluded from Git. The example has no real GPU UUIDs or LAN IP.
Review staged files before every push; `.gitignore` is not a secret scanner.

The default host binding is `127.0.0.1`. For a trusted LAN, set
`STRATA_BIND_HOST=0.0.0.0`; the entrypoint still refuses an empty API key. Use TLS
or a secure tunnel on untrusted networks. Do not forward the HTTP port publicly.
Metrics require authentication; `/health` is public.

Only the utility-only power-policy service has SYS_ADMIN. It has no network or
model/secret mounts, checks the caps every 30 seconds, and repairs resets.
Stopping it does not restore previous power limits. Stop it before manual power
experiments. The server has no SYS_ADMIN.

```sh
docker compose stop                  # stop both services
docker compose up -d --no-build       # restart
docker compose down                  # retain named state volume and model files
```

Do not routinely use `down -v`. Runtime config/logs are in the `strata-state`
volume; they are not required to rebuild the deployment, and conversation parking
is in-memory only. Back up volume contents separately if you want retained logs
or other runtime settings. Keep this Git repo and the model/key backups available
outside the rig before wiping it.

## Updating and checking

Never run `git submodule update --remote` blindly: it moves off the tested commit.
To deliberately upgrade, select a source commit in `vendor/Strata`, build, test
quality/cache switching/long-context behavior, and commit the new submodule pointer.

```sh
git submodule update --init --recursive
python3 -m unittest discover -s tests -v
```

Original-rig cache smoke test (2026-10-05): A → B → A restored 1984 of 1991 prompt
tokens and produced the same deterministic answer. It did not measure sustained
multi-client or long-context cache performance. This repo's portable Compose
wrapper has static/unit validation; its clean-machine build and live deployment
must still be verified. Creating it does not change the original running stack.
