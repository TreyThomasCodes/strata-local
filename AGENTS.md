# Agent guide

## Scope

This repo deploys upstream's prebuilt Strata CUDA image on Linux, 128 GB RAM, and two
NVLink RTX 3090s. It stores deployment settings, not models or secrets. Keep local code
to what upstream lacks: UUID-bound GPU order, power caps, and the saved engine settings.

- `compose.yaml` pins the image by digest and defines the server, power-policy
  service, GPU order, and mounts. The server runs upstream's `serve/server.py`.
- `config/strata-iq3_s.json` holds the saved engine settings and container paths.
- `config/strata-orca-iq3_xxs.json` is the opt-in Orca comparison profile. It
  must match the saved engine settings; `STRATA_CONFIG` selects it.
- `SETTINGS.md` records operator rationales, test evidence, and tuning limits.
- `docker/power-policy.py` enforces UUID-bound power caps and checks readback.
- `tests/test_deployment.py` tests settings, GPU order, serving flags, and caps.
- `.env.example` documents host paths, GPU UUIDs, power limits, and port binding.
- `vendor/Strata` is a pinned submodule at the image's release tag. It supplies the
  Grafana dashboard and the source reference. Read its `AGENTS.md` before editing it.

## Change rules

Keep changes scoped to the task. Preserve the image digest, the submodule pin, and
saved settings unless the task requires an upgrade. Move the digest and the submodule
together. Never run `git submodule update --remote` blindly. Read
`vendor/Strata/docs/AI_SETUP.md` and `docs/DOCKER.md` before changing image or model setup.

Keep primary and peer GPUs distinct and UUID-bound. The primary maps to logical
CUDA0; the peer maps to logical CUDA1. `CUDA_VISIBLE_DEVICES` in `compose.yaml` sets
the order. Keep `gpu` and `gpu_roles` out of the configs; the server would replace
that order. Default caps are 300 W and 350 W.

Keep the default host binding at `127.0.0.1`. The operator serves the trusted LAN
without an API key; the server runs with `--no-api-key`. Do not add a key back unless
the operator asks or exposure goes beyond the LAN.

Keep SYS_ADMIN confined to the utility-only power-policy service. Preserve its
network isolation and lack of model mounts. Keep model mounts read-only.

Do not start or stop services, change GPU power limits, rotate keys, or delete
volumes without explicit user authorization. The rig can have a running stack.
`docker compose down -v` deletes runtime state. Stopping power-policy does not
restore earlier caps.

## Validate

Run the unit tests after changes:

```sh
python3 -m unittest discover -s tests -v
```

Validate Compose when `.env` contains the required UUIDs and paths:

```sh
docker compose config --quiet
```

Review `git diff --check`, the diff, and staged files. Keep secrets, real host
identifiers, model artifacts, logs, and backups out of commits. `.gitignore` is
not a secret scanner.

Report checks run and checks skipped. Unit tests and Compose validation do not
prove the image or a live deployment. An authorized live check must verify
health, a completion, metrics, GPU ordering, and power caps.
Upgrades also need quality, cache-switching, and long-context tests.

## Write

Use short, direct sentences. Keep articles and technical terms exact. Use the
pattern: the thing acts for a reason; then give the next step. Fragments are fine
when clear. Cut filler, pleasantries, and hedging. Preserve code blocks during
prose-only edits. State validation limits as facts. Separate operator rationale
from measured results. Ask for missing rationales; never invent them.
