#!/bin/bash
# Final deployment steps for Reedling HPC
# Run this script on Reedling: ssh -K user@hpc-login.example.com
# Then: bash ~/tequila-mule/finish_deployment.sh

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
echo "This will take 10-30 minutes depending on network speed..."
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
echo "[4/5] Installing tequila-mule package..."
cd ~/tequila-mule
pip3 install --user -e .
echo "✓ Package installed"

# Step 5: Verify installation
echo "[5/5] Verifying installation..."
if command -v tequila-mule &> /dev/null; then
    tequila-mule --version
    echo "✓ Installation verified"
else
    echo "✗ tequila-mule not in PATH"
    echo "Add to PATH: export PATH=\$HOME/.local/bin:\$PATH"
    exit 1
fi

echo ""
echo "=========================================="
echo "Deployment Complete! 🚀"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✓ Container: vLLM 0.4.2 sandbox (11GB)"
echo "  ✓ Model: Qwen2.5-Coder-7B-Instruct (~15GB)"
echo "  ✓ Package: tequila-mule installed"
echo ""
echo "Next steps:"
echo ""
echo "1. Create an API key:"
echo "   tequila-mule add-key user@example.com"
echo ""
echo "2. Test the gateway (foreground):"
echo "   tequila-mule start --foreground"
echo ""
echo "3. In another terminal, test the API:"
echo "   curl http://localhost:8000/v1/models -H 'Authorization: Bearer YOUR_API_KEY'"
echo ""
echo "4. Deploy as background service:"
echo "   nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &"
echo "   echo \$! > ~/.tequila-mule/gateway.pid"
echo ""
echo "5. Check status:"
echo "   tequila-mule status"
echo ""
echo "Documentation:"
echo "  - Quick reference: ~/tequila-mule/QUICK_REFERENCE.md"
echo "  - Full guide: ~/tequila-mule/REEDLING_DEPLOYMENT.md"
echo "  - Status: ~/tequila-mule/STATUS.md"
echo ""
