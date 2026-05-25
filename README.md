# tequila-mule

An OpenAI-compatible gateway service that provides stable, continuous inference API access backed by dynamically scheduled LLM jobs on Slurm-managed HPC clusters.

## Overview

**tequila-mule** solves a specific problem: on HPC systems with strict wall-time limits and no dedicated service infrastructure, how do you provide a persistent inference endpoint?

The answer: run overlapping rolling vLLM job reservations on the cluster, and have a lightweight gateway on the login node that automatically rotates to a new backend before the current job is killed by the scheduler. Clients never see a gap.

## Features

- **OpenAI-compatible API** — drop-in replacement for clients using `openai` SDK or `curl`
- **No API changes needed** — works with existing LangChain, Pi.ai, or custom client code
- **Transparent job rotation** — gateway swaps backends without dropping requests
- **User-level permissions** — no admin privileges required; runs as a regular user
- **Simple deployment** — `pip install` and a config file; designed for researchers, not SREs

## Quick Start

### Prerequisites

- Python 3.10+
- Access to a Slurm cluster with GPU nodes
- vLLM installed on compute nodes (or in a shared venv)
- Shared filesystem (NFS) accessible from login and compute nodes

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

### Running

Start the gateway:

```bash
tequila-mule start
```

This will submit the first vLLM job and enter a holding pattern (`503 Retry-After`) until the backend is ready. Estimated wait time is printed to stdout.

Once the backend is warm, the gateway accepts requests at `http://localhost:8080` (configurable).

Test it:

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3-8B-Instruct",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### Command Reference

```bash
tequila-mule start          # Start the gateway (foreground)
tequila-mule status         # Show current backend, job IDs, health
tequila-mule rotate         # Manually force an immediate rotation (testing)
tequila-mule stop           # Graceful shutdown
tequila-mule logs           # Tail gateway and job logs
```

## Architecture

Three core components:

1. **Gateway** — FastAPI app on the login node, proxies requests to active vLLM backend
2. **Lifecycle Manager** — Background thread that submits new Slurm jobs before current job expires, orchestrates rotation
3. **Health Monitor** — Background thread that polls backend health, triggers rotation on failure

See [CLAUDE.md](CLAUDE.md) for detailed architecture and development notes.

## Configuration

See `tequila-mule.toml` for all options. Key sections:

- `[gateway]` — host, port, API key, request retry window
- `[slurm]` — partition, GPU request, wall-time, lead-time, job overlap count, port range
- `[model]` — model name and vLLM arguments
- `[paths]` — config file locations, state file, logs directory

## Deployment

For production, use `nohup` or systemd user unit:

```bash
nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
```

The gateway is designed to run as a persistent process on the login node. On restart, it rehydrates job state from `~/.tequila-mule/state.json` and resumes normal operation.

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

- Single model per gateway instance (run multiple instances on different ports to serve multiple models)
- Single shared API key (suitable for research teams, not multi-tenant scenarios)
- Slurm only (abstraction layer designed for future SGE/PBS support)
- No web UI

## Support

For issues, feature requests, or contributions, see the [GitHub repository](https://github.com/crashfrog/tequila-mule).

---

*Named after a drink at a party. You weren't there.*
