# tequila-mule

An OpenAI-compatible gateway service that provides stable, continuous inference API access backed by dynamically scheduled LLM jobs on Slurm-managed HPC clusters.

## Overview

**tequila-mule** solves a specific problem: on HPC systems with strict wall-time limits and no dedicated service infrastructure, how do you provide a persistent inference endpoint?

The answer: run overlapping rolling vLLM job reservations on the cluster, and have a lightweight gateway on the login node that automatically rotates to a new backend before the current job is killed by the scheduler. Clients never see a gap.

### Why not just use Ollama?

Ollama and vLLM solve a different problem than tequila-mule does. Ollama gives you an OpenAI-compatible API and model serving, same as vLLM — but it has no concept of Slurm, job wall-time, or backend rotation, and its multi-GPU support is layer-splitting (like llama.cpp), not true tensor parallelism, so it can't match vLLM's throughput for large models split across multiple GPUs (e.g. `--tensor-parallel-size 2`). It also has no multi-user API key management.

tequila-mule's value is the scheduling/rotation glue *around* a serving engine (Slurm job submission, lead-time rotation, health-checked failover, API keystore) — swapping the backend from vLLM to Ollama wouldn't remove any of that code, and would cost you tensor parallelism on multi-GPU jobs.

## Features

- **OpenAI-compatible API** — drop-in replacement for clients using `openai` SDK or `curl`
- **No API changes needed** — works with existing LangChain, Pi.ai, or custom client code
- **Transparent job rotation** — gateway swaps backends without dropping requests
- **Multi-model hosting** — run several independently-rotating model pools (e.g. a large model on multiple GPUs plus small models on single GPUs) behind one endpoint, routed by model name or alias, similar to AWS Bedrock
- **User-level permissions** — no admin privileges required; runs as a regular user
- **Simple deployment** — `pip install` and a config file; designed for researchers, not SREs

### Multi-model routing

A gateway instance can manage any number of backend pools, each with its own Slurm sizing, model, and rotation timeline. Configure them as `[[backends]]` entries in the TOML (see `tequila-mule.toml`):

```toml
[[backends]]
name = "llama-3.3-70b"
aliases = ["llama", "default"]
[backends.slurm]
gres = "gpu:h100:2"
port = 50000
[backends.model]
name = "meta-llama/Llama-3.3-70B-Instruct"
vllm_extra_args = "--tensor-parallel-size 2"

[[backends]]
name = "small-model-a"
aliases = ["small", "fast"]
[backends.slurm]
gres = "gpu:h100:1"
port = 50001
[backends.model]
name = "..."
```

Clients target a pool by sending either its exact model name or one of its aliases in the `model` field:

```bash
curl ... -d '{"model": "small", "messages": [...]}'
```

Each pool runs its own independent Slurm job lifecycle (submission, rotation, health checks) — one pool rotating or cold-starting never affects another. An unrecognized `model` value returns `400`. `GET /v1/models` lists the canonical model name and every alias for each currently-live pool.

Existing single-model configs (top-level `[slurm]`/`[model]`, no `[[backends]]`) keep working unchanged — they're automatically treated as one backend pool named `"default"`.

## Quick Start

### Prerequisites

- Python 3.10+
- Access to a Slurm cluster with GPU nodes
- vLLM Singularity container (or venv with vLLM installed)
- Shared filesystem (NFS) accessible from login and compute nodes
- Model weights pre-downloaded to HuggingFace cache (for air-gapped compute nodes)

### Installation

```bash
pip install tequila-mule
# or with uv
uv pip install tequila-mule
```

### Configuration

Copy the example config and customize for your cluster:

```bash
mkdir -p ~/.tequila-mule
cp tequila-mule.toml ~/.tequila-mule/
# Edit ~/.tequila-mule/tequila-mule.toml with your partition, wall-time, model, etc.
```

### First-Time Setup (air-gapped clusters)

If running on air-gapped compute nodes, pre-stage container and model weights:

```bash
# On login node (has internet access)
mkdir -p ~/containers
singularity pull ~/containers/vllm-openai.sif docker://vllm/vllm-openai:latest

# Pre-download model weights
pip install --user huggingface-cli
huggingface-cli download meta-llama/Llama-3.1-8B
```

Update config paths to match your environment (see `tequila-mule.toml`).

### Running

Generate API key (recommended):

```bash
tequila-mule add-key your.email@example.com
# Save the generated key for client configuration
```

Start the gateway:

```bash
tequila-mule start
```

This will submit the first vLLM job and enter a holding pattern (`503 Retry-After`) until the backend is ready. Check status in another terminal:

```bash
tequila-mule status
```

Once the backend is warm, the gateway accepts requests at `http://localhost:8765` (configurable).

Test it:

```bash
# Get your API key (use email from add-key command)
export OPENAI_API_KEY=$(tequila-mule show-key your.email@example.com | grep -o 'sk-[^ ]*')

curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

### Command Reference

```bash
tequila-mule start                  # Start the gateway (foreground)
tequila-mule status                 # Show current backend, job IDs, health
tequila-mule stop                   # Graceful shutdown (Ctrl+C in start terminal)

# API key management
tequila-mule add-key <email>        # Create API key for user
tequila-mule list-keys              # List all API keys
tequila-mule show-key [email]       # Show key for email (or all keys)
tequila-mule revoke-key <key|email> # Revoke API key
```

## Architecture

Three core components, each instantiated **once per configured backend pool**:

1. **Gateway** — FastAPI app on the login node; routes each request to the backend pool owning the requested model name/alias, and proxies to that pool's active vLLM backend
2. **Lifecycle Manager** — one per backend pool; submits new Slurm jobs before that pool's current job expires, orchestrates rotation independently of other pools
3. **Health Monitor** — one per backend pool; polls that pool's backend health, triggers rotation on failure

See [CLAUDE.md](CLAUDE.md) for detailed architecture and development notes.

## Configuration

See `tequila-mule.toml` for all options. Key sections:

- `[gateway]` — host, port, request retry window
- `[[backends]]` — one entry per model pool; each has its own `[backends.slurm]` (partition, GPU request, wall-time, lead-time, port) and `[backends.model]` (model name, vLLM arguments), plus an `aliases` list
- `[paths]` — config file locations, state file, logs directory

Legacy top-level `[slurm]`/`[model]` tables (no `[[backends]]`) are still supported and are migrated automatically into a single `"default"` backend pool.

## Deployment

**Deploying on a new cluster?** Start with **[AGENTS.md](AGENTS.md)** — a
cluster-agnostic deployment guide written for an agent or engineer bringing
tequila-mule up on a grid it wasn't built for. It walks the filesystem/bind-mount,
container-version, model-fit, and connectivity gotchas in order, with a
failure→cause quick reference. (Site operators may keep a private,
cluster-specific companion doc with already-solved values for their own grid;
such files are gitignored and not part of this public repo.)

For production, use `nohup` or systemd user unit:

```bash
nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
```

The gateway is designed to run as a persistent process on the login node. On restart, it rehydrates each backend pool's job state from its own `~/.tequila-mule/state-<pool-name>.json` and resumes normal operation. (A pool named `"default"` — the legacy single-model shape — falls back to the older `~/.tequila-mule/state.json` if its own state file doesn't exist yet, so upgrading an existing single-model deployment in place doesn't lose track of an already-running job.)

## Development

See [CLAUDE.md](CLAUDE.md) for setup, testing, and linting commands.

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run type checking and linting
mypy tequila_mule/
ruff check tequila_mule/
```

## Limitations (v1)

- Aliases are static: fixed in the TOML, changed only by editing config and restarting (no runtime alias re-pointing/blue-green model swaps)
- Single shared API key set across all backend pools (suitable for research teams, not per-model or multi-tenant access control)
- Slurm only (abstraction layer designed for future SGE/PBS support)
- No web UI

## Support

For issues, feature requests, or contributions, see the [GitHub repository](https://github.com/crashfrog/tequila-mule).

---

*Named after a drink at a party. You weren't there.*
