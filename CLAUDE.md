# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**tequila-mule** is a lightweight gateway service providing an OpenAI-compatible inference API backed by dynamically scheduled LLM jobs on a Slurm-managed HPC cluster. The system maintains continuous API availability by running overlapping rolling vLLM job reservations, automatically rotating to a new backend before the current job is killed by the scheduler.

**Key design constraint**: Operates entirely within user-level Slurm permissions on login nodes with no dedicated service infrastructure—simple enough for a single researcher to deploy.

See `/tequila-mule-PRD.md` (or the PRD passed at init time) for full requirements.

## Agent Skills

### Issue tracker

Issues are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels track issue state: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Project Structure

```
tequila-mule/
├── tequila_mule/
│   ├── __init__.py
│   ├── gateway.py              # FastAPI app, OpenAI-compatible proxy
│   ├── lifecycle.py            # Job submission & rotation logic
│   ├── health.py               # Backend health monitoring
│   ├── keystore.py             # API key management (multi-user)
│   ├── cli.py                  # Command-line interface
│   ├── config.py               # Config loading & validation
│   └── templates/
│       └── vllm_job.sh.j2      # Slurm job template (Jinja2)
├── tests/
│   ├── test_gateway.py
│   ├── test_lifecycle.py
│   ├── test_keystore.py
│   ├── test_health.py
│   └── test_config.py
├── pyproject.toml              # Dependencies & package metadata
├── tequila-mule.toml           # Example config (user copies to ~/.tequila-mule/)
└── README.md                   # Installation & quickstart
```

## Architecture Overview

The system has three core moving parts:

1. **Gateway** (FastAPI process on login node)
   - OpenAI-compatible `/v1/chat/completions`, `/v1/completions`, `/v1/models` endpoints
   - Maintains reference to current active backend, proxies requests via httpx with streaming
   - Exposes internal registration endpoint (`POST /internal/register`) for backends to announce themselves
   - Queues or retries requests during backend rotation (configurable window, default 30s)

2. **Lifecycle Manager** (background thread in gateway)
   - Tracks job state: `{job_id, node, port, status, submitted_at, expires_at}`
   - Submits new Slurm job at `wall_time - lead_time` before current job expiry
   - Polls `squeue`/`scontrol` until new job reaches `RUNNING`
   - Waits for registration callback from new job (with polling fallback)
   - Atomically swaps active backend once new job passes health check
   - On cold start: submits immediately and blocks until backend is available

3. **Health Monitor** (background thread in gateway)
   - Periodically polls `GET /health` on active backend
   - On failure: marks unhealthy, triggers emergency lifecycle check
   - Distinguishes between unreachable node vs. slow backend

**Job rotation timeline example:**
- T+0h: Job A submitted, running. Gateway routes to A.
- T+20h: Lifecycle submits Job B (lead_time=4h before T+24h wall).
- T+20h: Job B runs, vLLM loads, registers with gateway.
- T+21h: Gateway health-checks B, flips to B.
- T+24h: Job A killed by Slurm. Zero client impact.
- T+44h: Cycle repeats with Job C.

**Request handling during flip:**
During the backend flip window, incoming requests are held in an asyncio queue (configurable timeout). The flip is fast (~5s), so this is transparent to clients.

**Cold start:**
On first launch with no running jobs, gateway enters `503 / Retry-After` pattern and submits immediately. Clients see `503` with estimated wait time until first backend warms.

## Development Workflow

### Setup

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Or with uv (preferred on HPC systems)
uv pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_gateway.py

# Run a specific test
pytest tests/test_gateway.py::test_proxy_chat_completions

# Run with coverage
pytest --cov=tequila_mule tests/

# Run only integration tests (require Slurm mock)
pytest -m integration
```

### Linting & Type Checking

```bash
# Format code
ruff format tequila_mule/ tests/

# Lint (includes import sorting)
ruff check tequila_mule/ tests/ --fix

# Type checking
mypy tequila_mule/

# Run all checks (lint + type + tests)
make check
```

### Running Locally

```bash
# Start gateway (reads tequila-mule.toml from CWD)
tequila-mule start

# Show current status
tequila-mule status

# Force manual rotation (testing)
tequila-mule rotate

# Tail logs
tequila-mule logs

# Graceful shutdown
tequila-mule stop
```

### Config

The gateway reads `tequila-mule.toml` from the current directory or `~/.tequila-mule/tequila-mule.toml`. Example values are in the repo; users copy and customize for their cluster.

Key config sections:
- `[gateway]`: host, port, api_key, request_retry_window_seconds
- `[slurm]`: partition, gres, wall_time, lead_time_minutes, overlap_jobs, port_range
- `[model]`: name, vllm_extra_args
- `[paths]`: job_template, state_file, log_dir

## Key Implementation Details

### State Persistence
- Job state stored in `~/.tequila-mule/state.json` (configurable)
- On gateway restart, lifecycle re-checks `squeue` to rehydrate and validate
- If all jobs are dead, gateway cold-starts

### Slurm Job Submission
- Template: `tequila_mule/templates/vllm_job.sh.j2`
- Rendered with live parameters (job_id, port, model, api_key for internal comms)
- Job posts to gateway `/internal/register` once vLLM is accepting requests
- Job traps `SIGTERM` to post to `/internal/deregister` before expiry

### Backend Registration & Health
- Registration endpoint is internal-only (no auth check; assumes login-node-only access)
- Health monitor distinguishes "unreachable" (node died) vs. "slow" (under load)
- Failed health checks trigger emergency checks in lifecycle manager

### Async Request Handling
- All request proxying is async via httpx
- Streaming responses are properly handled (chunked transfer)
- During rotation, requests are queued in asyncio.Queue with timeout

## Testing Strategy

- **Unit tests** mock Slurm CLI calls and httpx requests
- **Integration tests** require a running Slurm cluster or mock squeue/scontrol
- **Fixtures** provided for common mocks: mock job state, mock Slurm responses, fake vLLM backend
- Prioritize testing lifecycle transitions (cold start, rotation, backend failure, recovery)

## Common Gotchas

1. **Port conflicts**: Fixed port (50000) must not conflict with existing services on compute nodes
2. **Wall-time alignment**: `wall_time` config must match cluster policy; misalignment causes unexpected job kills
3. **Lead time too short**: If `lead_time_minutes` is too small, new job may not reach RUNNING before current job expires
4. **Shared filesystem**: vLLM model weights and Singularity container must be accessible from both login and compute nodes
5. **API key management**: Each key tied to an email; use `tequila-mule add-key <email>` to create, tracks last_used timestamp
6. **Air-gapped compute nodes**: Pre-download container and model weights on login node before first run

## Deployment Notes

**Recommended invocation** (for production):
```bash
nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
```

Or as systemd user unit if environment supports `loginctl enable-linger`.

**Monitoring**:
- `tequila-mule status` shows current backend, job IDs, expiry times, health
- Logs in `~/.tequila-mule/logs/` (configurable)
- Health monitor probes are verbose in logs for troubleshooting

## Future Extensions (Out of Scope v1)

- SGE/PBS support (job submission abstraction is designed for swapping)
- Multi-model routing (run multiple gateway instances on different ports as workaround)
- Autoscaling (submit additional jobs under load—natural extension of lifecycle manager)
- Web dashboard (`tequila-mule status --web` for HTML status page)
