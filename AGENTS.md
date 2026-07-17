# AGENTS.md — Deploying tequila-mule on a new HPC cluster

This guide is for an **agent (or engineer) deploying tequila-mule on a grid other
than the one it was first built for**. It captures the cluster-specific gotchas
that are *not* visible from the code and that will otherwise be rediscovered the
hard way, one failed Slurm job at a time.

This document is the general method. If your site keeps a private,
cluster-specific companion doc with already-solved values (host names, scratch
paths, module names, etc.), start there for the concrete numbers and use this as
the reasoning behind them. Such site docs are gitignored and not part of this
public repo. A specific cluster (H100 nodes, Slurm, Singularity) is used below
only as a worked example.

For architecture and dev workflow, see `CLAUDE.md`. For the request/rotation model,
see `README.md`.

---

## The mental model in one paragraph

tequila-mule runs a FastAPI gateway on a **login node**. It submits vLLM jobs to
**compute nodes** via Slurm, waits for each job to register back, and rotates
backends before Slurm kills them. Almost every deployment failure is one of:
(1) the compute node can't see the files the login node can, (2) the container's
vLLM is too old for the model, (3) the model won't fit or won't capture CUDA
graphs on that GPU topology, or (4) the login node can't submit/see jobs. Work
through the checklist below in order and you will catch these before they cost you
a multi-minute job launch each.

---

## Deployment checklist (do these in order)

### 1. Discover the filesystem layout — do NOT assume

The single most common failure is a path that exists on the login node but not
inside the container on the compute node, or vice versa.

- **Find the real scratch filesystem.** It is cluster-specific: `/scratch`,
  `/nfs/scratch`, `/lscratch`, `/flash/...`, `$SCRATCH`, etc. Do not guess — probe
  it, and confirm it is **shared** (visible from both login and compute nodes) and
  **large** (model weights are tens to hundreds of GB).

  ```bash
  # examples of probing; the answer differs per cluster
  echo "$SCRATCH"; ls -ld /scratch /nfs/scratch /lscratch /flash 2>/dev/null
  df -h <candidate>          # capacity + that it's a real mount
  ```

- **Put weights, containers, and caches on scratch, NOT in `$HOME`.** Home quotas
  are typically small (e.g. 100 GB) and home may not be the fastest mount. All of
  `[paths]` (`container`, `model_cache`, `state_file`, `log_dir`) should live under
  scratch.

- **Verify the compute node sees scratch.** A path being readable from the login
  node proves nothing.

  ```bash
  srun -p <gpu-partition> --gres=<gres> --time=00:02:00 \
    bash -c 'ls -d <scratch-path> && hostname'
  ```

### 2. Bind-mount scratch into the container

Singularity/Apptainer does **not** auto-mount arbitrary paths. If your weights or
container live on `/nfs/...` (or any non-default mount), the container will report:

```
OSError: Incorrect path_or_model_id: '/nfs/scratch/.../model'
```

The job template (`tequila_mule/templates/vllm_job.sh.j2`) already passes
`--bind {{ bind_path | default('/nfs') }}`. **If your scratch is not under `/nfs`,
you must change the bind path** — either edit the default in the template, or (once
wired through) supply `bind_path` at render time in `lifecycle.py`. Confirm with:

```bash
srun ... singularity exec --nv --bind <scratch-mount> <container> \
  bash -c 'ls <model-path> | head'
```

### 3. Use a container whose vLLM is new enough for your models

Model support tracks the vLLM/transformers version tightly. An old container fails
at **config load**, before any GPU work, with errors like:

- `ValueError: model type 'gemma3' ... Transformers does not recognize this architecture`
  (container predates the model family), or
- `ValueError: 'rope_scaling' must be a dictionary with two fields ...`
  (container predates Llama 3.1+ rope scaling).

Pull a **recent, pinned** tag rather than `:latest` (reproducibility, and `latest`
drifts). Match the container's CUDA build to the node driver (check
`nvidia-smi` on a compute node).

```bash
# pinned example — pick a current version, verify the tag exists first
singularity pull --name vllm-vX.Y.Z.sif \
  docker://vllm/vllm-openai:vX.Y.Z-<arch>-<cuda>-<os>
```

**Build the SIF on a compute node, not the login node.** `mksquashfs` for a ~10 GB
image is memory-hungry and segfaults (exit 139) under tight login-node limits.
Point the build cache/tmp at scratch and submit it as a job:

```bash
export APPTAINER_CACHEDIR=<scratch>/.sing-cache APPTAINER_TMPDIR=<scratch>/.sing-tmp
# run inside an sbatch/srun with adequate --mem (e.g. 64G)
```

The container's entrypoint is `python3 -m vllm.entrypoints.openai.api_server`. The
bare `vllm` CLI is **not reliably on `PATH`** on compute nodes; the template invokes
the module form for this reason. Keep it that way unless you've verified the CLI
resolves on a compute node.

### 4. Pre-fetch model weights — safetensors only, and mind gated repos

- **Download to scratch, keep the HF cache off `$HOME`:** set `HF_HOME=<scratch>/hf-cache`.
- **Prefer safetensors** and exclude pickle formats (`.bin`/`.pth`/`.ckpt`) for
  supply-chain safety. Use an **allowlist**, and note the `hf` CLI takes **one
  pattern per flag** (repeat `--include`, don't pass multiple values to one flag,
  or it treats them as literal filenames and downloads nothing):

  ```bash
  hf download <repo> --local-dir <scratch>/models/<name> \
    --include "*.safetensors" --include "*.json" --include "*.txt" --include "*.model" \
    --exclude "*.bin" --exclude "*.pth" --exclude "*.ckpt"
  ```

- **Gated models** (Llama, Gemma, etc.) need a **valid HF user access token** whose
  account has accepted the model license. An `hf_oauth…` token is a short-lived
  session token and will be rejected as invalid — use a durable token from
  `huggingface.co/settings/tokens` via `hf auth login`. Non-gated mirrors (e.g.
  Red Hat / Neural Magic FP8 builds) need no token at all.
- **Verify the download:** shard count matches the `*.index.json` weight map, and no
  pickle files landed.

### 5. Right-size the model for the GPUs, and expect a CUDA-graph gotcha

- **Fit weights entirely in VRAM.** A 70B model in **FP8** (~71 GB) fits 2×80 GB
  with real KV-cache headroom; the same model in **BF16** (~140 GB) technically
  fits but leaves almost nothing for KV cache, throttling concurrency/context. FP8
  compressed-tensors builds load natively on recent vLLM.
- **Never use `--cpu-offload-gb` for an interactive backend.** It streams weights
  over PCIe every forward pass and cripples decode. It only exists to fit a model
  that otherwise won't load at all.
- **Redirect all caches to scratch** so CUDA-graph / torch-compile artifacts don't
  fill a small node-local `/tmp` (symptom: `OSError: [Errno 28] No space left on
  device` during graph capture). Set `VLLM_CACHE_ROOT`, `XDG_CACHE_HOME`,
  `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`, `TMPDIR` under scratch (via
  `SINGULARITYENV_*` so they cross into the container).
- **CUDA graph capture can crash on some multi-GPU topologies.** Symptom: the model
  loads fully, then dies at "Capturing CUDA graphs" with
  `CUDA error: an illegal memory access was encountered` (seen in the
  `trtllm_mnnvl_allreduce` kernel). Mitigations, in order:
  1. `--disable-custom-all-reduce` (fall back to NCCL) — may not be enough,
  2. `--enforce-eager` — skips graph capture entirely; slower per token but stable.

  On Reedling's H100 nodes, only `--enforce-eager` worked for the TP-2 FP8 Llama.
  Drop the flag and retry after a container/vLLM upgrade to reclaim graph-mode speed.

### 6. Confirm login-node ↔ compute-node connectivity

The gateway waits for each job to POST to `/internal/register`. If compute nodes
can't reach the login node's gateway port, jobs run but never register.

```bash
# from inside a compute-node job:
curl http://<login-node>:<gateway-port>/health
```

If this fails, you need the polling fallback (gateway polls `squeue`/`scontrol`
instead of waiting for the callback), or a reachable host/port.

### 7. Align Slurm sizing with cluster policy

- `wall_time` must match what the partition actually allows, or jobs get killed
  unexpectedly.
- `lead_time_minutes` must exceed typical queue wait, or the replacement job won't
  reach `RUNNING` before the current one expires and clients see a gap.
- The `port` must be free on compute nodes and (if you rely on registration)
  reachable from the login node.

---

## Smoke test before declaring success

Loading the gateway is not proof. Actually serve a completion end to end. A minimal
manual test per model, on a compute node:

```bash
srun -p <gpu-partition> --gres=<gres> --time=00:10:00 \
  singularity exec --nv --bind <scratch-mount> <container> \
  python3 -m vllm.entrypoints.openai.api_server \
    --model <weights-path> --tensor-parallel-size <N> \
    --max-model-len 2048 --port 50055 <any-required-flags> &
# then, once /health returns 200:
curl -s localhost:50055/v1/completions -H 'Content-Type: application/json' \
  -d '{"model":"<weights-path>","prompt":"The capital of France is","max_tokens":8,"temperature":0}'
```

A correct answer ("... Paris ...") confirms weights, quantization, tensor
parallelism, and inference all work. Only then wire the values into the config and
start the gateway.

---

## Failure → cause quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `Incorrect path_or_model_id` | scratch not bind-mounted into container | add/fix `--bind <scratch-mount>` (step 2) |
| `does not recognize this architecture` / `rope_scaling` ValueError | container vLLM too old for the model | pin a newer container (step 3) |
| `mksquashfs ... exit status 139` on pull | building SIF on resource-limited login node | build on a compute node with `--mem` + scratch tmp (step 3) |
| `vllm: command not found` on compute node | CLI shim not on PATH | use `python3 -m vllm.entrypoints.openai.api_server` (step 3) |
| `hf download` fetches 0 files | multiple globs passed to one `--include` | repeat the flag once per pattern (step 4) |
| `Invalid user token` on gated model | `hf_oauth…` session token expired | `hf auth login` with a durable access token (step 4) |
| `No space left on device` during graph capture | compile/graph cache on small node-local `/tmp` | redirect caches to scratch via `SINGULARITYENV_*` (step 5) |
| `illegal memory access` at "Capturing CUDA graphs" | graph capture unstable on this GPU topology | `--disable-custom-all-reduce`, then `--enforce-eager` (step 5) |
| Job RUNNING but gateway never flips to it | compute node can't reach login-node gateway port | fix connectivity or use polling fallback (step 6) |
| Replacement job late; clients see a gap | `lead_time_minutes` < queue wait | raise `lead_time_minutes` (step 7) |
