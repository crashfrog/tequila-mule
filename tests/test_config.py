"""Tests for config module."""

import tempfile

import pytest

from tequila_mule.config import BackendPoolConfig, Config, load_config


def test_config_defaults():
    """Test default configuration."""
    config = Config()

    assert config.gateway.host == "127.0.0.1"
    assert config.gateway.port == 8765

    # No [[backends]] and default legacy slurm/model -> migrated to "default"
    assert len(config.backends) == 1
    default_backend = config.backends[0]
    assert default_backend.name == "default"
    assert default_backend.slurm.partition == "gpu"
    assert default_backend.slurm.gpus_per_job == 2
    assert default_backend.slurm.wall_time == "23:00:00"
    assert default_backend.slurm.lead_time_minutes == 90
    assert default_backend.model.name == "meta-llama/Llama-3.1-8B"

    assert config.paths.api_keys_file == "~/.tequila-mule/api_keys.json"


def test_config_from_dict(sample_config_data):
    """Test config creation from dict (legacy single-model shape)."""
    config = Config(**sample_config_data)

    assert config.gateway.port == 8765
    assert len(config.backends) == 1
    assert config.backends[0].name == "default"
    assert config.backends[0].slurm.partition == "gpu"
    assert config.backends[0].model.name == "meta-llama/Llama-3.1-8B"


def test_config_migration_from_legacy_shape(sample_config_data):
    """Test that old-style [slurm]/[model] TOML (no [[backends]]) migrates
    into a single "default" backend pool, so existing deployments don't
    need to change their config file."""
    config = Config(**sample_config_data)

    assert config.backends == [
        BackendPoolConfig(
            name="default",
            model=config.model,
            slurm=config.slurm,
        )
    ]


def test_multi_backend_config(sample_multi_backend_config_data):
    """Test explicit [[backends]] config with aliases."""
    config = Config(**sample_multi_backend_config_data)

    assert len(config.backends) == 2
    names = {b.name for b in config.backends}
    assert names == {"llama-3.3-70b", "small-model-a"}

    llama = next(b for b in config.backends if b.name == "llama-3.3-70b")
    assert llama.aliases == ["llama", "default"]
    assert llama.model.name == "meta-llama/Llama-3.3-70B-Instruct"

    small = next(b for b in config.backends if b.name == "small-model-a")
    assert small.aliases == ["small", "fast"]


def test_duplicate_backend_names_rejected(sample_multi_backend_config_data):
    """Backend pool names must be unique."""
    data = sample_multi_backend_config_data
    data["backends"][1]["name"] = data["backends"][0]["name"]

    with pytest.raises(ValueError):
        Config(**data)


def test_duplicate_aliases_rejected(sample_multi_backend_config_data):
    """Aliases must be unique across all backends."""
    data = sample_multi_backend_config_data
    data["backends"][1]["aliases"] = ["small", "llama"]

    with pytest.raises(ValueError):
        Config(**data)


def test_alias_colliding_with_backend_name_rejected(sample_multi_backend_config_data):
    """Aliases must not collide with any backend's canonical name or model name."""
    data = sample_multi_backend_config_data
    data["backends"][1]["aliases"] = ["small", "llama-3.3-70b"]

    with pytest.raises(ValueError):
        Config(**data)


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
    assert config.backends[0].slurm.partition == "gpu"


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
