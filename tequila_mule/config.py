"""Configuration loading and validation."""

import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class GatewayConfig(BaseModel):
    """Gateway server configuration."""

    host: str = "127.0.0.1"
    port: int = 8765


class SlurmConfig(BaseModel):
    """Slurm job configuration."""

    partition: str = "gpu"
    gres: str = "gpu:h100:2"
    gpus_per_job: int = 2
    wall_time: str = "23:00:00"
    lead_time_minutes: int = 90
    port: int = 50000  # Fixed port for vLLM on compute nodes

    @field_validator("wall_time")
    @classmethod
    def validate_wall_time(cls, v: str) -> str:
        """Validate wall time format (HH:MM:SS or D-HH:MM:SS)."""
        parts = v.split("-")
        if len(parts) == 2:
            time_part = parts[1]
        elif len(parts) == 1:
            time_part = parts[0]
        else:
            raise ValueError("Invalid wall_time format")

        time_components = time_part.split(":")
        if len(time_components) != 3:
            raise ValueError("wall_time must be HH:MM:SS or D-HH:MM:SS")
        return v


class ModelConfig(BaseModel):
    """Model configuration."""

    name: str = "meta-llama/Llama-3.1-8B"
    vllm_extra_args: str = "--tensor-parallel-size 2 --gpu-memory-utilization 0.95"


class PathsConfig(BaseModel):
    """Path configuration."""

    container_path: str = "/home/user/containers/vllm-openai.sif"
    job_template: str = "tequila_mule/templates/vllm_job.sh.j2"
    state_file: str = "~/.tequila-mule/state.json"
    log_dir: str = "~/.tequila-mule/logs"
    api_keys_file: str = "~/.tequila-mule/api_keys.json"


class Config(BaseModel):
    """Root configuration."""

    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    slurm: SlurmConfig = Field(default_factory=SlurmConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from TOML file.

    Search order:
    1. Provided path
    2. ./tequila-mule.toml
    3. ~/.tequila-mule/tequila-mule.toml

    Returns default config if no file found.
    """
    if config_path and config_path.exists():
        paths_to_try = [config_path]
    else:
        paths_to_try = [
            Path("tequila-mule.toml"),
            Path.home() / ".tequila-mule" / "tequila-mule.toml",
        ]

    for path in paths_to_try:
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return Config(**data)

    # Return default config if no file found
    return Config()
