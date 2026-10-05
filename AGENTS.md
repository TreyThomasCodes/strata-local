# Agent guide

## Scope

This repo wraps a pinned Strata source build for Linux, 128 GB RAM, and two NVLink
RTX 3090s. It stores deployment code, not models or secrets.

- `compose.yaml` defines the server, power-policy service, GPU access, and mounts.
- `config/strata-iq3_s.json` holds the saved engine settings and container paths.
- `docker/entrypoint.py` validates the key and GPU UUIDs, writes runtime config,
  and starts the server.
- `docker/power-policy.py` enforces UUID-bound power caps and checks readback.
- `tests/test_deployment.py` tests settings, key handling, GPU order, and caps.
- `.env.example` documents host paths, GPU UUIDs, power limits, and port binding.
- `vendor/Strata` is a pinned submodule. Read its `AGENTS.md` before editing it.

## Change rules

Keep changes scoped to the task. Preserve the source pin and saved settings unless
the task requires an upgrade. Never run `git submodule update --remote` blindly.
Read `vendor/Strata/docs/AI_SETUP.md` before changing build or model setup.

Keep primary and peer GPUs distinct and UUID-bound. The primary maps to logical
CUDA0; the peer maps to logical CUDA1. Default caps are 300 W and 350 W.

Keep authentication mandatory and the default host binding at `127.0.0.1`.
The API key comes from the Compose secret and reaches the server through
`STRATA_API_KEY`. Never put it in runtime JSON, image layers, command-line
arguments, logs, or Git.

Keep SYS_ADMIN confined to the utility-only power-policy service. Preserve its
network isolation and lack of model/secret mounts. Keep model mounts read-only.

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
prove a CUDA build or live deployment. An authorized live check must verify
health, an authenticated completion, metrics, GPU ordering, and power caps.
Upgrades also need quality, cache-switching, and long-context tests.

## Write

Use short, direct sentences. Keep articles and technical terms exact. Use the
pattern: the thing acts for a reason; then give the next step. Fragments are fine
when clear. Cut filler, pleasantries, and hedging. Preserve code blocks during
prose-only edits. State validation limits as facts.
