# tequila-mule Quick Reference - Reedling HPC

## Essential Commands

```bash
# Start gateway
tequila-mule start [--foreground]

# Check status
tequila-mule status

# Stop gateway
tequila-mule stop

# View logs
tequila-mule logs
tail -f ~/.tequila-mule/logs/gateway.log

# API key management
tequila-mule add-key <email>
tequila-mule list-keys
tequila-mule revoke-key <email>

# Force rotation (testing)
tequila-mule rotate
```

## File Locations

```
~/.tequila-mule/
├── tequila-mule.toml          # Configuration
├── vllm_job.sh.j2             # Slurm job template
├── state.json                 # Job state persistence
├── keystore.db                # API keys
├── logs/
│   ├── gateway.log            # Gateway logs
│   └── slurm-*.out            # Slurm job logs
├── models/
│   └── Qwen2.5-Coder-7B-Instruct/  # Model weights
└── containers/
    └── vllm-openai_latest.sif      # vLLM container
```

## Configuration Highlights

**Current Setup:**
- Partition: `gpu` (H100 GPUs)
- GPU: 1x H100 per job
- Wall time: 48 hours
- Lead time: 6 hours (job submits 6h before expiry)
- Model: Qwen2.5-Coder-7B-Instruct
- Context: 8192 tokens
- Port: 50000-50099 range

**Gateway:** http://hpc-login.example.com:8000

## API Usage

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://hpc-login.example.com:8000/v1",
    api_key="YOUR_API_KEY"
)

response = client.chat.completions.create(
    model="Qwen2.5-Coder-7B-Instruct",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### cURL

```bash
curl http://hpc-login.example.com:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen2.5-Coder-7B-Instruct", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Monitoring Slurm

```bash
# Your jobs
squeue -u $USER

# Job details
scontrol show job JOBID

# Time remaining
squeue -j JOBID -o "%T %M %L"

# Cancel job
scancel JOBID
```

## Troubleshooting

**503 Service Unavailable**
→ Cold start in progress. Wait 3-10 minutes for first backend.

**Job fails immediately**
→ Check: `tail -50 ~/.tequila-mule/logs/slurm-JOBID.out`

**Backend never registers**
→ Network issue between compute and login node. Check logs.

**Port already in use**
→ Adjust `port_range` in config.

**Model not found**
→ Verify: `ls ~/.tequila-mule/models/Qwen2.5-Coder-7B-Instruct/`

**Container not found**
→ Verify: `ls ~/.tequila-mule/containers/vllm-openai_latest.sif`

## Status Interpretation

```
Current Backend: http://gpu-node-01:50000
Job ID: 12345
Status: healthy
Expires: 2026-06-30 12:00:00
Next submission: 2026-06-30 06:00:00
```

**Healthy rotation:**
- Current job running
- Next job submits at `expires - lead_time`
- Seamless switch before expiry
- No downtime

## Performance Expectations

- **Throughput**: 100-150 tokens/sec
- **Latency**: <500ms first token
- **Concurrent users**: 50+
- **Cold start**: 3-10 minutes
- **Rotation**: 5-10 seconds (transparent)

## Production Deployment

```bash
# Background service
nohup tequila-mule start > ~/.tequila-mule/logs/gateway.log 2>&1 &
echo $! > ~/.tequila-mule/gateway.pid

# Check it's running
ps aux | grep tequila-mule

# Stop later
kill $(cat ~/.tequila-mule/gateway.pid)
```

## Common Config Changes

**Longer jobs (less rotation overhead):**
```toml
wall_time = "120:00:00"    # 5 days (max)
lead_time_minutes = 720    # 12 hours
```

**Testing (fast rotation):**
```toml
partition = "gpu-tst"
wall_time = "00:30:00"     # 30 minutes
lead_time_minutes = 10     # 10 minutes
```

**Larger context:**
```toml
vllm_extra_args = [
    "--max-model-len", "16384",  # 16K context
    ...
]
```

## Support Resources

- Reedling Docs: https://hfp-support-docs.fda.gov/wordpress/reedling-hpc-overview
- Full deployment guide: `REEDLING_DEPLOYMENT.md`
- vLLM docs: https://docs.vllm.ai/
