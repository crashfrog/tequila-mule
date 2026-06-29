#!/bin/bash
# Deployment script for tequila-mule on FDA Reedling HPC
set -euo pipefail

REMOTE_HOST="user@hpc-login.example.com"
REMOTE_HOME="/home/user"

echo "=========================================="
echo "tequila-mule Deployment to Reedling HPC"
echo "=========================================="

# Step 1: Check SSH connectivity
echo "[1/7] Checking SSH connectivity..."
if ! ssh -K ${REMOTE_HOST} "echo 'SSH connection successful'" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to ${REMOTE_HOST}"
    echo "Make sure you can SSH with: ssh -K ${REMOTE_HOST}"
    exit 1
fi
echo "✓ SSH connection OK"

# Step 2: Install huggingface_hub for model download
echo "[2/7] Installing huggingface_hub on remote..."
ssh -K ${REMOTE_HOST} "pip3 install --user huggingface_hub tqdm" 2>&1 | tail -5
echo "✓ Dependencies installed"

# Step 3: Download model weights
echo "[3/7] Downloading Qwen2.5-Coder-7B-Instruct model (this may take a while)..."
echo "Model size: ~15GB"
ssh -K ${REMOTE_HOST} "cd ~/.tequila-mule/models && python3 << 'PYEOF'
from huggingface_hub import snapshot_download
import os

model_dir = 'Qwen2.5-Coder-7B-Instruct'
if os.path.exists(model_dir):
    print(f'Model already exists at {model_dir}')
else:
    print('Downloading model...')
    snapshot_download(
        repo_id='Qwen/Qwen2.5-Coder-7B-Instruct',
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )
    print('Model download complete!')
PYEOF
" 2>&1
echo "✓ Model ready"

# Step 4: Pull vLLM container (with retry logic)
echo "[4/7] Pulling vLLM container..."
echo "Note: Container is ~10GB and may take 15-45 minutes"
ssh -K ${REMOTE_HOST} "
cd ~/.tequila-mule/containers
if [ -f vllm-openai_latest.sif ]; then
    echo 'Container already exists'
else
    echo 'Pulling container (this may take a while)...'
    # Try pulling with memory-efficient options
    SINGULARITY_TMPDIR=/tmp singularity pull docker://vllm/vllm-openai:v0.4.2 || {
        echo 'Failed with latest, trying specific stable version...'
        SINGULARITY_TMPDIR=/tmp singularity pull docker://vllm/vllm-openai:v0.4.2
    }
fi
ls -lh vllm-openai*.sif
"
echo "✓ Container ready"

# Step 5: Copy configuration files
echo "[5/7] Deploying configuration files..."
scp -K tequila-mule-reedling.toml ${REMOTE_HOST}:~/.tequila-mule/tequila-mule.toml
scp -K vllm_job_reedling.sh.j2 ${REMOTE_HOST}:~/.tequila-mule/vllm_job.sh.j2
echo "✓ Configuration files deployed"

# Step 6: Transfer tequila-mule package
echo "[6/7] Deploying tequila-mule package..."
ssh -K ${REMOTE_HOST} "mkdir -p ~/tequila-mule"
rsync -avz -e "ssh -K" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='*.egg-info' \
    ./ ${REMOTE_HOST}:~/tequila-mule/
echo "✓ Package deployed"

# Step 7: Install tequila-mule
echo "[7/7] Installing tequila-mule on remote..."
ssh -K ${REMOTE_HOST} "cd ~/tequila-mule && pip3 install --user -e ."
echo "✓ Installation complete"

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. SSH to Reedling: ssh -K ${REMOTE_HOST}"
echo "2. Create an API key: tequila-mule add-key your.email@fda.gov"
echo "3. Start the gateway: nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &"
echo "4. Check status: tequila-mule status"
echo ""
echo "Configuration file: ~/.tequila-mule/tequila-mule.toml"
echo "Logs directory: ~/.tequila-mule/logs/"
echo ""
