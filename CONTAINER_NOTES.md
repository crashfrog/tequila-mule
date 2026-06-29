# vLLM Container Download Notes for Reedling

## Issue Encountered

Initial attempt to pull `vllm/vllm-openai:latest` failed with:
```
FATAL: While making image from oci registry: error fetching image to cache: 
while building SIF from layers: while creating squashfs: 
/usr/libexec/apptainer/bin/mksquashfs command failed: 
exit status 134: malloc(): corrupted top size
```

**Root cause**: Memory corruption during large container conversion (vLLM container is ~10GB)

## Solutions

### Option 1: Use Specific Stable Version (Recommended)

Instead of `:latest`, use a known stable version:

```bash
cd ~/.tequila-mule/containers
SINGULARITY_TMPDIR=/tmp singularity pull docker://vllm/vllm-openai:v0.4.2
```

**Update config to match:**
```toml
[paths]
container = "~/.tequila-mule/containers/vllm-openai_v0.4.2.sif"
```

### Option 2: Pull on Compute Node

Compute nodes may have more available memory:

```bash
# Submit interactive job
srun -p gpu --gres=gpu:h100:1 --mem=128GB --pty bash

# Pull container
cd ~/.tequila-mule/containers
singularity pull docker://vllm/vllm-openai:v0.4.2

# Exit when done
exit
```

### Option 3: Use Pre-built Container from Shared Storage

Check if vLLM is already available in shared software:

```bash
ls /nfs/software/containers/ | grep -i vllm
ls /nfs/software/apps/ | grep -i vllm
```

If found, update config to point to shared container:
```toml
[paths]
container = "/nfs/software/containers/vllm-openai.sif"
```

### Option 4: Build from Docker Archive (Advanced)

```bash
# On a machine with Docker (may need to do locally)
docker pull vllm/vllm-openai:v0.4.2
docker save vllm/vllm-openai:v0.4.2 -o vllm-openai.tar

# Transfer to Reedling
scp -K vllm-openai.tar user@hpc-login.example.com:~/.tequila-mule/containers/

# Convert on Reedling
cd ~/.tequila-mule/containers
singularity build vllm-openai_v0.4.2.sif docker-archive://vllm-openai.tar
rm vllm-openai.tar
```

### Option 5: Request from HPC Support

Contact Reedling support to install vLLM in shared software:

> "Could you please install the vLLM Singularity container in /nfs/software/containers/ 
> for use across the cluster? We need vllm/vllm-openai:v0.4.2 or later."

## Recommended Versions

| Version | Release Date | Notes |
|---------|--------------|-------|
| v0.4.2 | 2024-04 | Stable, well-tested |
| v0.4.3 | 2024-05 | Current stable |
| v0.5.0 | 2024-06 | Latest features, H100 optimizations |
| latest | Rolling | May be unstable |

**For production**: Use v0.4.2 or v0.4.3  
**For cutting-edge features**: Use v0.5.0

## Workaround Applied in Deployment Script

The deployment script now:
1. Checks if container already exists
2. Uses `SINGULARITY_TMPDIR=/tmp` for more memory space
3. Falls back to specific version (v0.4.2) if latest fails
4. Reports detailed error messages

## Manual Container Pull (Current Recommendation)

Until the deployment script is run, you can manually pull the container:

```bash
ssh -K user@hpc-login.example.com

# Navigate to containers directory
cd ~/.tequila-mule/containers

# Remove failed partial download if exists
rm -f vllm-openai_latest.sif

# Pull specific stable version with tmp dir set
SINGULARITY_TMPDIR=/tmp singularity pull --name vllm-openai_v0.4.2.sif docker://vllm/vllm-openai:v0.4.2

# Verify download
ls -lh vllm-openai_v0.4.2.sif
singularity inspect vllm-openai_v0.4.2.sif
```

**Then update config:**
```bash
nano ~/.tequila-mule/tequila-mule.toml
# Change container path to:
# container = "~/.tequila-mule/containers/vllm-openai_v0.4.2.sif"
```

## Alternative: Native vLLM Installation

If container continues to fail, you can install vLLM natively:

```bash
# Load CUDA if available
module load cuda/12.1  # or available version

# Install vLLM
pip3 install --user vllm

# Update job template to use native vLLM instead of singularity
# Replace:
#   singularity exec --nv ${CONTAINER} python3 -m vllm.entrypoints.openai.api_server
# With:
#   python3 -m vllm.entrypoints.openai.api_server
```

**Job template changes needed:**
```bash
# Remove container binding, just run directly
~/.local/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_PATH}/${MODEL_NAME} \
    --host 0.0.0.0 \
    --port ${PORT} \
    ${VLLM_ARGS}
```

## Status Check

To check current container status:

```bash
ssh -K user@hpc-login.example.com "ls -lh ~/.tequila-mule/containers/"
```

Expected output when successful:
```
-rwxr-xr-x 1 user user-pgid 10.5G Jun 29 10:15 vllm-openai_v0.4.2.sif
```

## Next Steps

1. Choose one of the solutions above
2. Verify container is accessible: `singularity exec <container> python3 -c "import vllm; print(vllm.__version__)"`
3. Update config file with correct container path
4. Proceed with model download
5. Test gateway startup
