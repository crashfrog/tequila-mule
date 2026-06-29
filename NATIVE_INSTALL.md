# Native vLLM Installation (Container Alternative)

Since the Singularity/Apptainer container build is failing due to squashfs issues, we can install vLLM natively instead.

## Option 1: Native pip Install (Recommended)

### Step 1: Install on Compute Node

Submit an interactive job to access GPU and CUDA:

```bash
ssh -K user@hpc-login.example.com
srun -p gpu-tst --gres=gpu:h100:1 --mem=32GB --time=2:00:00 --pty bash
```

### Step 2: Install vLLM

```bash
# Install vLLM with CUDA support
pip3 install --user vllm

# Verify installation
python3 -c "import vllm; print(f'vLLM version: {vllm.__version__}')"
```

### Step 3: Update Job Template

Modify `~/.tequila-mule/vllm_job.sh.j2` to use native vLLM instead of container:

```bash
# OLD (container-based):
# singularity exec --nv ${CONTAINER} python3 -m vllm.entrypoints.openai.api_server ...

# NEW (native):
~/.local/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_PATH}/${MODEL_NAME} \
    --host 0.0.0.0 \
    --port ${PORT} \
    ${VLLM_ARGS} &
```

### Step 4: Update Configuration

Edit `~/.tequila-mule/tequila-mule.toml`:

```toml
[paths]
# Comment out or remove container line
# container = "~/.tequila-mule/containers/vllm-openai_v0.4.2.sif"
model_cache = "~/.tequila-mule/models"
job_template = "~/.tequila-mule/vllm_job.sh.j2"
```

## Option 2: Sandbox Directory (If Option 1 Fails)

Currently testing: building as sandbox directory instead of SIF file.

```bash
cd ~/.tequila-mule/containers
singularity build --sandbox vllm-sandbox docker://vllm/vllm-openai:v0.4.2
```

Use in job template:
```bash
singularity exec --nv \
    --writable-tmpfs \
    ${HOME}/.tequila-mule/containers/vllm-sandbox \
    python3 -m vllm.entrypoints.openai.api_server ...
```

## Complete Native Job Template

Here's the full modified job template for native vLLM:

```bash
#!/bin/bash
#SBATCH --job-name=tequila-mule-vllm
#SBATCH --partition={{ partition }}
#SBATCH --gres={{ gres }}
#SBATCH --cpus-per-task={{ cpus_per_task }}
#SBATCH --mem={{ memory }}
#SBATCH --time={{ wall_time }}
#SBATCH --output={{ log_dir }}/slurm-%j.out
#SBATCH --error={{ log_dir }}/slurm-%j.err

set -euo pipefail

JOB_ID=${SLURM_JOB_ID}
NODE=$(hostname)
PORT={{ port }}
MODEL_NAME="{{ model_name }}"
MODEL_PATH="{{ model_path }}"
GATEWAY_URL="{{ gateway_url }}"
INTERNAL_API_KEY="{{ internal_api_key }}"

echo "=========================================="
echo "tequila-mule vLLM Backend Job (Native)"
echo "=========================================="
echo "Job ID: ${JOB_ID}"
echo "Node: ${NODE}"
echo "Port: ${PORT}"
echo "Model: ${MODEL_NAME}"
echo "Started: $(date)"
echo "=========================================="

trap 'echo "Received SIGTERM, deregistering..."; curl -X POST "${GATEWAY_URL}/internal/deregister" -H "X-Internal-Key: ${INTERNAL_API_KEY}" -d "{\"job_id\": \"${JOB_ID}\"}"; exit 0' SIGTERM

export CUDA_VISIBLE_DEVICES=0
export NCCL_DEBUG=INFO

VLLM_ARGS="{{ vllm_extra_args | join(' ') }}"

echo "Starting vLLM server (native installation)..."

# Use native vLLM installation
~/.local/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_PATH}/${MODEL_NAME} \
    --host 0.0.0.0 \
    --port ${PORT} \
    ${VLLM_ARGS} &

VLLM_PID=$!
echo "vLLM server started with PID: ${VLLM_PID}"

# Wait for vLLM to be ready
echo "Waiting for vLLM server to be ready..."
MAX_RETRIES=60
RETRY_INTERVAL=5
for i in $(seq 1 ${MAX_RETRIES}); do
    if curl -s -f http://localhost:${PORT}/health > /dev/null 2>&1; then
        echo "vLLM server is ready!"
        break
    fi
    if [ $i -eq ${MAX_RETRIES} ]; then
        echo "ERROR: vLLM server failed to start"
        kill ${VLLM_PID} 2>/dev/null || true
        exit 1
    fi
    echo "Retry $i/${MAX_RETRIES}: waiting ${RETRY_INTERVAL}s..."
    sleep ${RETRY_INTERVAL}
done

# Register with gateway
echo "Registering with gateway at ${GATEWAY_URL}..."
for i in $(seq 1 10); do
    if curl -X POST "${GATEWAY_URL}/internal/register" \
        -H "Content-Type: application/json" \
        -H "X-Internal-Key: ${INTERNAL_API_KEY}" \
        -d "{\"job_id\": \"${JOB_ID}\", \"node\": \"${NODE}\", \"port\": ${PORT}}" \
        -f -s > /dev/null 2>&1; then
        echo "Successfully registered with gateway!"
        break
    fi
    sleep 5
done

echo "=========================================="
echo "vLLM backend serving requests"
echo "Endpoint: http://${NODE}:${PORT}"
echo "=========================================="

# Monitor process
while kill -0 ${VLLM_PID} 2>/dev/null; do
    sleep 60
    if curl -s -f http://localhost:${PORT}/health > /dev/null 2>&1; then
        echo "[$(date)] Health check: OK"
    else
        echo "[$(date)] Health check: FAILED"
        kill ${VLLM_PID} 2>/dev/null || true
        exit 1
    fi
done

echo "vLLM process exited"
exit 0
```

## Installation Commands Summary

```bash
# Connect to HPC
ssh -K user@hpc-login.example.com

# Get interactive GPU node
srun -p gpu-tst --gres=gpu:h100:1 --mem=32GB --time=2:00:00 --pty bash

# Install vLLM
pip3 install --user vllm

# Verify
python3 -c "import vllm; print(vllm.__version__)"

# Exit compute node
exit

# Update job template (copy native version above)
nano ~/.tequila-mule/vllm_job.sh.j2

# Test
tequila-mule start --foreground
```

## Benefits of Native Install

1. **No container issues**: Avoids squashfs compression bugs
2. **Faster startup**: No container overhead
3. **Easier debugging**: Direct access to Python environment
4. **Simpler updates**: `pip3 install --upgrade vllm`
5. **Better integration**: Uses system CUDA directly

## Drawbacks

1. **Less portable**: Depends on system CUDA version
2. **Version management**: Manual updates needed
3. **Dependency conflicts**: Possible with other packages

## Which to Use?

- **Native install**: Recommended for Reedling given container issues
- **Sandbox**: If you need container isolation
- **SIF container**: Once Reedling fixes squashfs issues

## Next Steps

Once vLLM is installed (native or sandbox):

1. Download model: See `REEDLING_DEPLOYMENT.md` 
2. Update config and job template as shown above
3. Test: `tequila-mule start --foreground`
4. Deploy: `nohup tequila-mule start &`
