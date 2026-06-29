# Deployment Status - 2026-06-29 15:05

## ✅ Container Download Complete

After encountering issues with SIF format compression, successfully built vLLM container in **sandbox format** (directory-based).

**Container Details:**
- Location: `~/.tequila-mule/containers/vllm-sandbox/`
- Size: 11GB
- Version: vLLM 0.4.2
- Format: Singularity sandbox (directory)
- Status: ✅ Verified working

## Configuration Updated

### Files Updated:

1. **`tequila-mule-reedling.toml`**
   - Container path now points to sandbox: `~/.tequila-mule/containers/vllm-sandbox`

2. **`vllm_job_reedling.sh.j2`**
   - Added `--writable-tmpfs` flag for sandbox containers
   - All other settings remain the same

## Current Deployment State

| Component | Status | Location |
|-----------|--------|----------|
| **Container** | ✅ Ready | `~/.tequila-mule/containers/vllm-sandbox/` (11GB) |
| **Model** | ⏳ Pending | Need to download Qwen2.5-Coder-7B-Instruct |
| **Configuration** | ✅ Ready | `tequila-mule-reedling.toml` |
| **Job Template** | ✅ Ready | `vllm_job_reedling.sh.j2` |
| **Directories** | ✅ Ready | `~/.tequila-mule/{logs,models,containers}` |

## Next Steps

### 1. Download Model Weights (~15GB)

```bash
ssh -K user@hpc-login.example.com

# Install huggingface_hub
pip3 install --user huggingface_hub

# Download model
cd ~/.tequila-mule/models
python3 << 'EOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-Coder-7B-Instruct',
    local_dir='Qwen2.5-Coder-7B-Instruct',
    local_dir_use_symlinks=False
)
EOF
```

**Estimated time:** 10-30 minutes

### 2. Deploy Configuration Files

```bash
# From local machine
scp -K tequila-mule-reedling.toml user@hpc-login.example.com:~/.tequila-mule/tequila-mule.toml
scp -K vllm_job_reedling.sh.j2 user@hpc-login.example.com:~/.tequila-mule/vllm_job.sh.j2
```

### 3. Install tequila-mule Package

```bash
ssh -K user@hpc-login.example.com

cd ~/tequila-mule
pip3 install --user -e .

# Verify installation
tequila-mule --version
```

### 4. Create API Key

```bash
tequila-mule add-key user@example.com
# Save the generated key!
```

### 5. Test Gateway (Foreground)

```bash
tequila-mule start --foreground
```

Watch for:
- ✅ Job submission
- ✅ Job reaches RUNNING state
- ✅ Backend registration
- ✅ Health check passes
- ✅ "Ready to accept requests"

### 6. Test API

```bash
# In another terminal
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"

curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Write a Python function to calculate fibonacci numbers"}],
    "max_tokens": 500
  }'
```

### 7. Deploy as Background Service

Once testing works:

```bash
# Stop foreground instance (Ctrl+C)

# Start as background service
nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
echo $! > ~/.tequila-mule/gateway.pid

# Verify it's running
tequila-mule status
```

## Container Format: Sandbox vs SIF

**What we're using:** Sandbox (directory format)

**Why:**
- Reedling's Apptainer has a bug in squashfs compression for large containers
- Sandbox format avoids compression, works reliably
- Functionally identical to SIF for our use case

**Differences:**

| Feature | SIF (Failed) | Sandbox (Working) |
|---------|--------------|-------------------|
| Format | Single compressed file | Directory structure |
| Size | ~6GB compressed | ~11GB uncompressed |
| Performance | Slightly faster startup | Negligible difference |
| Reliability | ❌ Crashes on Reedling | ✅ Works perfectly |
| Usage | `singularity exec file.sif` | `singularity exec dir/` |

**Job template difference:**
```bash
# Sandbox requires --writable-tmpfs flag
singularity exec --nv --writable-tmpfs vllm-sandbox python3 -m vllm...
```

## Troubleshooting Container

### Verify Container Works

```bash
# Test Python import
singularity exec ~/.tequila-mule/containers/vllm-sandbox \
  python3 -c "import vllm; print(vllm.__version__)"

# Should output: 0.4.2

# Test with GPU (on compute node)
srun -p gpu-tst --gres=gpu:h100:1 --pty bash
singularity exec --nv ~/.tequila-mule/containers/vllm-sandbox \
  nvidia-smi
```

### Container Permissions

If you get permission errors:

```bash
chmod -R u+rwX ~/.tequila-mule/containers/vllm-sandbox
```

### Rebuild Container

If needed:

```bash
cd ~/.tequila-mule/containers
rm -rf vllm-sandbox
singularity build --sandbox vllm-sandbox docker://vllm/vllm-openai:v0.4.2
```

## Estimated Timeline to Production

| Phase | Duration | Status |
|-------|----------|--------|
| Container download | 20-45 min | ✅ Complete (11GB) |
| Model download | 10-30 min | ⏳ Next |
| Config deployment | 2-5 min | ⏳ Next |
| Package install | 2-5 min | ⏳ Next |
| Cold start test | 5-10 min | ⏳ Later |
| **Total remaining** | **~20-50 min** | **Ready to proceed** |

## Documentation Reference

- **Full deployment guide**: `REEDLING_DEPLOYMENT.md`
- **Quick reference**: `QUICK_REFERENCE.md`
- **Native install alternative**: `NATIVE_INSTALL.md`
- **Container troubleshooting**: `CONTAINER_NOTES.md`
- **Configuration summary**: `DEPLOYMENT_SUMMARY.md`

## Success Criteria

✅ Container: Downloaded and verified (vLLM 0.4.2 in sandbox format)  
⏳ Model: Need to download Qwen2.5-Coder-7B-Instruct  
⏳ Gateway: Need to start and test  
⏳ API: Need to verify endpoints work  
⏳ Rotation: Need to observe first job rotation  

## Current Blockers

**None!** Container issue resolved. Ready to proceed with model download.

## Quick Commands

```bash
# Check container
ls -lh ~/.tequila-mule/containers/vllm-sandbox/

# Download model (run on Reedling)
pip3 install --user huggingface_hub && cd ~/.tequila-mule/models && python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-Coder-7B-Instruct', local_dir='Qwen2.5-Coder-7B-Instruct', local_dir_use_symlinks=False)"

# Deploy configs (run locally)
scp -K tequila-mule-reedling.toml vllm_job_reedling.sh.j2 user@hpc-login.example.com:~/.tequila-mule/

# Install and test (run on Reedling)
cd ~/tequila-mule && pip3 install --user -e . && tequila-mule --version
```

---

**Status**: Container ready ✅ | Model pending ⏳ | ~30 minutes to production 🚀
