"""Tests for config module."""

import tempfile
from pathlib import Path

import pytest

from tequila_mule.config import Config, load_config


def test_config_defaults():
    """Test default configuration."""
    config = Config()

    assert config.gateway.host == "127.0.0.1"
    assert config.gateway.port == 8765

    assert config.slurm.partition == "gpu"
    assert config.slurm.gpus_per_job == 2
    assert config.slurm.wall_time == "23:00:00"
    assert config.slurm.lead_time_minutes == 90

    assert config.model.name == "meta-llama/Llama-3.1-8B"
    assert config.paths.api_keys_file == "~/.tequila-mule/api_keys.json"


def test_config_from_dict(sample_config_data):
    """Test config creation from dict."""
    config = Config(**sample_config_data)

    assert config.gateway.port == 8765
    assert config.slurm.partition == "gpu"
    assert config.model.name == "meta-llama/Llama-3.1-8B"


def test_wall_time_validation():
    """Test wall_time format validation."""
    from tequila_mule.config import SlurmConfig

    # Valid formats
    SlurmConfig(wall_time="23:00:00")
    SlurmConfig(wall_time="1-12:30:00")

    # Invalid formats
    with pytest.raises(ValueError):
        SlurmConfig(wall_time="invalid")

    with pytest.raises(ValueError):
        SlurmConfig(wall_time="23:00")  # Missing seconds


def test_load_config_from_file(sample_config_data, tmp_path):
    """Test loading config from TOML file."""
    import tomli_w

    config_file = tmp_path / "test-config.toml"
    with open(config_file, "wb") as f:
        tomli_w.dump(sample_config_data, f)

    config = load_config(config_file)

    assert config.gateway.port == 8765
    assert config.slurm.partition == "gpu"


def test_load_config_default_when_no_file():
    """Test loading default config when no file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Change to temp dir where no config exists
        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            config = load_config()
            assert config.gateway.port == 8765  # Default value
        finally:
            os.chdir(old_cwd)
