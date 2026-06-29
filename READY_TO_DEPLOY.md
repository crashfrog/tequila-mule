# Ready to Deploy - Final Steps

## Current Status

✅ **Container**: vLLM 0.4.2 sandbox built and verified (11GB)  
✅ **Configuration**: Production-ready config created  
✅ **Job Template**: Reedling-specific template ready  
✅ **Documentation**: Complete deployment guides created  
⏳ **Model**: Ready to download (~15GB, 10-30 min)  
⏳ **Package**: Ready to install (2 min)  

## Quick Deploy (Copy & Paste)

### Step 1: SSH to Reedling and Transfer Files

```bash
# On your local machine
cd ~/tequila-mule

# Transfer config files (you'll need to do this manually via SSH)
# Since scp -K isn't working, we'll copy via SSH commands
```

### Step 2: Run Complete Deployment Script

```bash
# SSH to Reedling
ssh -K user@hpc-login.example.com

# Transfer the files manually
cat > ~/.tequila-mule/tequila-mule.toml << 'EOF'
# tequila-mule configuration for FDA Reedling HPC
# Copy to ~/.tequila-mule/tequila-mule.toml after reviewing

[gateway]
# Gateway runs on login node
host = "0.0.0.0"
port = 8000
# Retry window during backend rotation
request_retry_window_seconds = 30

[slurm]
# Reedling HPC Slurm configuration
partition = "gpu"
gres = "gpu:h100:1"
wall_time = "48:00:00"
lead_time_minutes = 360
overlap_jobs = 1
port_range = [50000, 50099]
memory = "64GB"
cpus_per_task = 12

[model]
name = "Qwen2.5-Coder-7B-Instruct"
vllm_extra_args = [
    "--tensor-parallel-size", "1",
    "--max-model-len", "8192",
    "--gpu-memory-utilization", "0.9",
    "--dtype", "auto",
    "--enable-prefix-caching",
    "--max-num-seqs", "256",
    "--enable-chunked-prefill",
]

[paths]
container = "~/.tequila-mule/containers/vllm-sandbox"
model_cache = "~/.tequila-mule/models"
job_template = "~/.tequila-mule/vllm_job.sh.j2"
state_file = "~/.tequila-mule/state.json"
log_dir = "~/.tequila-mule/logs"

[health]
check_interval = 30
timeout = 10
max_failures = 3

[api]
enable_chat_completions = true
enable_completions = true
enable_models = true
request_timeout = 300
max_tokens_limit = 8192
EOF

# Now run the automated deployment
bash << 'DEPLOY_SCRIPT'
#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "Finishing tequila-mule Deployment"
echo "=========================================="

# Step 1: Install huggingface_hub
echo "[1/5] Installing huggingface_hub..."
pip3 install --user huggingface_hub tqdm
echo "✓ Dependencies installed"

# Step 2: Download model
echo "[2/5] Downloading Qwen2.5-Coder-7B-Instruct (~15GB)..."
echo "This will take 10-30 minutes..."
cd ~/.tequila-mule/models

python3 << 'EOF'
from huggingface_hub import snapshot_download
import os

model_dir = 'Qwen2.5-Coder-7B-Instruct'
if os.path.exists(model_dir) and os.listdir(model_dir):
    print(f'Model already exists at {model_dir}')
else:
    print('Downloading model...')
    snapshot_download(
        repo_id='Qwen/Qwen2.5-Coder-7B-Instruct',
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )
    print('Model download complete!')
EOF

echo "✓ Model ready"

# Step 3: Verify model files
echo "[3/5] Verifying model files..."
if [ -f ~/.tequila-mule/models/Qwen2.5-Coder-7B-Instruct/config.json ]; then
    echo "✓ Model files verified"
    du -sh ~/.tequila-mule/models/Qwen2.5-Coder-7B-Instruct
else
    echo "✗ Model files missing!"
    exit 1
fi

# Step 4: Install tequila-mule package
echo "[4/5] Copying tequila-mule source..."
mkdir -p ~/tequila-mule
cd ~/tequila-mule

# You'll need to manually copy the source files
echo "Note: You'll need to copy the tequila-mule source code to ~/tequila-mule/"
echo "Or clone from git if available"

# Step 5: Success message
echo ""
echo "=========================================="
echo "Core Components Ready! 🚀"
echo "=========================================="
echo ""
echo "What's ready:"
echo "  ✓ Container: vLLM 0.4.2 sandbox (11GB)"
echo "  ✓ Model: Downloaded and verified"
echo "  ✓ Config: Deployed to ~/.tequila-mule/"
echo ""
echo "Still needed:"
echo "  - Copy tequila-mule source code to ~/tequila-mule/"
echo "  - Run: cd ~/tequila-mule && pip3 install --user -e ."
echo ""
DEPLOY_SCRIPT
```

## Alternative: Step-by-Step Manual Deployment

If the script above doesn't work, follow these manual steps:

### 1. Install Python Dependencies

```bash
ssh -K user@hpc-login.example.com
pip3 install --user huggingface_hub tqdm
```

### 2. Download Model

```bash
cd ~/.tequila-mule/models
python3 << 'EOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-Coder-7B-Instruct',
    local_dir='Qwen2.5-Coder-7B-Instruct',
    local_dir_use_symlinks=False
)
print('Download complete!')
EOF
```

**This will take 10-30 minutes.** You can monitor progress or let it run in background with:
```bash
nohup python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-Coder-7B-Instruct', local_dir='Qwen2.5-Coder-7B-Instruct', local_dir_use_symlinks=False)" &
```

### 3. Copy Source Code

From your local machine, transfer the tequila-mule source:

```bash
# Local machine
cd ~/tequila-mule
tar czf tequila-mule-src.tar.gz tequila_mule/ tests/ pyproject.toml README.md setup.py

# Transfer via SSH (you'll need to paste manually or use alternative method)
```

Or on Reedling, if you have git access:
```bash
cd ~
git clone <your-repo-url> tequila-mule
```

### 4. Install Package

```bash
cd ~/tequila-mule
pip3 install --user -e .

# Verify
~/.local/bin/tequila-mule --version
```

### 5. Create Job Template

Create `~/.tequila-mule/vllm_job.sh.j2` - I'll include the full template in a separate section below.

### 6. Create API Key

```bash
~/.local/bin/tequila-mule add-key user@example.com
```

**Save the generated API key!**

### 7. Test Gateway

```bash
~/.local/bin/tequila-mule start --foreground
```

Watch for successful job submission and backend registration.

### 8. Test API

In another terminal:

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 9. Deploy Production

```bash
# Stop foreground (Ctrl+C)
nohup ~/.local/bin/tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
echo $! > ~/.tequila-mule/gateway.pid
```

## Complete Job Template Content

Save this as `~/.tequila-mule/vllm_job.sh.j2`:

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
echo "tequila-mule vLLM Backend Job"
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

echo "Starting vLLM server..."

singularity exec --nv \
    --writable-tmpfs \
    --bind ${MODEL_PATH}:/models:ro \
    --bind $(pwd):/workspace \
    --pwd /workspace \
    ${HOME}/.tequila-mule/containers/vllm-sandbox \
    python3 -m vllm.entrypoints.openai.api_server \
    --model /models/${MODEL_NAME} \
    --host 0.0.0.0 \
    --port ${PORT} \
    ${VLLM_ARGS} &

VLLM_PID=$!
echo "vLLM server started with PID: ${VLLM_PID}"

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

## Files Already on Reedling

✅ Container: `~/.tequila-mule/containers/vllm-sandbox/` (11GB, verified working)  
✅ Directories: `~/.tequila-mule/{logs,models,containers}/` (created)  

## Files You Need to Transfer

📁 Configuration: `tequila-mule-reedling.toml` → `~/.tequila-mule/tequila-mule.toml`  
📁 Job Template: `vllm_job_reedling.sh.j2` → `~/.tequila-mule/vllm_job.sh.j2`  
📁 Source Code: `tequila_mule/` directory → `~/tequila-mule/`  

## Quick Verification Checklist

Before starting gateway:

```bash
# 1. Container exists and works
ls -lh ~/.tequila-mule/containers/vllm-sandbox/
singularity exec ~/.tequila-mule/containers/vllm-sandbox python3 -c "import vllm"

# 2. Model downloaded
ls -lh ~/.tequila-mule/models/Qwen2.5-Coder-7B-Instruct/

# 3. Config exists
cat ~/.tequila-mule/tequila-mule.toml

# 4. Job template exists
cat ~/.tequila-mule/vllm_job.sh.j2

# 5. Package installed
~/.local/bin/tequila-mule --version
```

## Success Criteria

When you run `tequila-mule start --foreground`, you should see:

1. ✅ "Submitting Slurm job..."
2. ✅ "Job XXXXX submitted successfully"
3. ✅ "Waiting for job to reach RUNNING state..."
4. ✅ "Backend registered: http://gXXX:50000"
5. ✅ "Active backend switched to http://gXXX:50000"
6. ✅ "Gateway ready to accept requests"

Then test:
```bash
curl http://localhost:8000/v1/models -H "Authorization: Bearer YOUR_KEY"
```

Should return JSON with model list.

## Need Help?

- **Full guide**: `REEDLING_DEPLOYMENT.md`
- **Quick commands**: `QUICK_REFERENCE.md`
- **Container issues**: `CONTAINER_NOTES.md`
- **Current status**: `STATUS.md`

## Estimated Time Remaining

- Model download: 10-30 minutes
- Package install: 2-5 minutes
- First test: 5-10 minutes
- **Total: ~20-45 minutes to production**

You're almost there! The hard part (container) is done. 🚀
