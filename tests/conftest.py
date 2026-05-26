"""Pytest fixtures."""

import pytest


@pytest.fixture
def sample_config_data():
    """Sample config data for testing."""
    return {
        "gateway": {
            "host": "127.0.0.1",
            "port": 8765,
        },
        "slurm": {
            "partition": "gpu",
            "gres": "gpu:h100:2",
            "gpus_per_job": 2,
            "wall_time": "23:00:00",
            "lead_time_minutes": 90,
            "port": 50000,
        },
        "model": {
            "name": "meta-llama/Llama-3.1-8B",
            "vllm_extra_args": "--tensor-parallel-size 2",
        },
        "paths": {
            "container_path": "/home/test/vllm.sif",
            "job_template": "tequila_mule/templates/vllm_job.sh.j2",
            "state_file": "~/.tequila-mule/state.json",
            "log_dir": "~/.tequila-mule/logs",
        },
    }
