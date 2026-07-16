"""Tests for lifecycle manager."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tequila_mule.config import Config
from tequila_mule.lifecycle import JobState, LifecycleManager


@pytest.fixture
def mock_gateway():
    """Mock gateway."""
    gateway = MagicMock()
    gateway.get_backend = MagicMock(return_value=None)
    gateway.set_backend = AsyncMock()
    return gateway


@pytest.fixture
def lifecycle_manager(mock_gateway, tmp_path):
    """Create lifecycle manager with temp state file."""
    config = Config()
    config.paths.state_file = str(tmp_path / "state.json")
    config.paths.job_template = "tequila_mule/templates/vllm_job.sh.j2"

    backend_config = config.backends[0]
    manager = LifecycleManager(
        backend_config, config.paths, "gw-host", 8765, mock_gateway
    )
    return manager


def test_job_state_serialization():
    """Test JobState can be serialized to JSON."""
    job = JobState(
        job_id="12345",
        node="gpu-node-01",
        port=50000,
        status="RUNNING",
        submitted_at="2026-05-26T10:00:00",
        expires_at="2026-05-27T09:00:00",
        backend_url="http://gpu-node-01:50000",
    )

    # Should be serializable
    from dataclasses import asdict

    data = asdict(job)
    assert data["job_id"] == "12345"
    assert data["node"] == "gpu-node-01"

    # Round-trip
    job2 = JobState(**data)
    assert job2.job_id == job.job_id


def test_save_and_load_state(lifecycle_manager):
    """Test state persistence."""
    # Create job state
    submitted_at = datetime.utcnow()
    expires_at = submitted_at + timedelta(hours=23)

    lifecycle_manager.current_job = JobState(
        job_id="12345",
        node="gpu-node-01",
        port=50000,
        status="RUNNING",
        submitted_at=submitted_at.isoformat(),
        expires_at=expires_at.isoformat(),
        backend_url="http://gpu-node-01:50000",
    )

    # Save state
    lifecycle_manager._save_state()

    # Clear in-memory state
    lifecycle_manager.current_job = None

    # Load state
    lifecycle_manager._load_state()

    # Verify
    assert lifecycle_manager.current_job is not None
    assert lifecycle_manager.current_job.job_id == "12345"
    assert lifecycle_manager.current_job.node == "gpu-node-01"


def test_two_managers_do_not_share_state(mock_gateway, tmp_path):
    """Two LifecycleManagers for different backends must write to separate
    per-backend state files and not clobber each other's state."""
    config = Config()
    config.paths.state_file = str(tmp_path / "state.json")
    config.paths.job_template = "tequila_mule/templates/vllm_job.sh.j2"

    backend_a = config.backends[0].model_copy(update={"name": "backend-a"})
    backend_b = config.backends[0].model_copy(update={"name": "backend-b"})

    manager_a = LifecycleManager(backend_a, config.paths, "gw-host", 8765, mock_gateway)
    manager_b = LifecycleManager(backend_b, config.paths, "gw-host", 8765, mock_gateway)

    assert manager_a.state_file != manager_b.state_file

    submitted_at = datetime.utcnow()
    expires_at = submitted_at + timedelta(hours=23)

    manager_a.current_job = JobState(
        job_id="aaa",
        node="g001",
        port=50000,
        status="RUNNING",
        submitted_at=submitted_at.isoformat(),
        expires_at=expires_at.isoformat(),
        backend_url="http://g001:50000",
    )
    manager_a._save_state()

    manager_b.current_job = JobState(
        job_id="bbb",
        node="g002",
        port=50001,
        status="RUNNING",
        submitted_at=submitted_at.isoformat(),
        expires_at=expires_at.isoformat(),
        backend_url="http://g002:50001",
    )
    manager_b._save_state()

    manager_a._load_state()
    manager_b._load_state()

    assert manager_a.current_job.job_id == "aaa"
    assert manager_b.current_job.job_id == "bbb"


def test_legacy_state_file_migration(mock_gateway, tmp_path):
    """A "default" backend with no per-backend state file yet should fall
    back to reading the legacy single-backend state.json, so an in-place
    upgrade doesn't lose track of an already-running job."""
    config = Config()
    config.paths.state_file = str(tmp_path / "state.json")
    config.paths.job_template = "tequila_mule/templates/vllm_job.sh.j2"

    legacy_manager = LifecycleManager(
        config.backends[0], config.paths, "gw-host", 8765, mock_gateway
    )
    # Simulate the pre-upgrade shape: write directly to legacy state.json
    legacy_manager.state_file = legacy_manager._legacy_state_file
    submitted_at = datetime.utcnow()
    expires_at = submitted_at + timedelta(hours=23)
    legacy_manager.current_job = JobState(
        job_id="legacy-1",
        node="g999",
        port=50000,
        status="RUNNING",
        submitted_at=submitted_at.isoformat(),
        expires_at=expires_at.isoformat(),
        backend_url="http://g999:50000",
    )
    legacy_manager._save_state()

    # New manager, as constructed post-upgrade, uses the new per-backend path
    new_manager = LifecycleManager(
        config.backends[0], config.paths, "gw-host", 8765, mock_gateway
    )
    assert new_manager.name == "default"
    assert not new_manager.state_file.exists()

    new_manager._load_state()

    assert new_manager.current_job is not None
    assert new_manager.current_job.job_id == "legacy-1"


@patch("tequila_mule.lifecycle.subprocess.run")
def test_submit_job(mock_subprocess_run, lifecycle_manager):
    """Test job submission."""
    # Mock sbatch response
    mock_subprocess_run.return_value = MagicMock(
        stdout=b"67890\n",
        returncode=0,
    )

    job_id = lifecycle_manager._submit_job()

    assert job_id == "67890"
    mock_subprocess_run.assert_called_once()

    # Verify sbatch was called with correct args
    call_args = mock_subprocess_run.call_args
    assert call_args[0][0] == ["sbatch", "--parsable"]


@patch("tequila_mule.lifecycle.subprocess.run")
def test_get_job_info(mock_subprocess_run, lifecycle_manager):
    """Test querying job info from squeue."""
    # Mock squeue response
    mock_subprocess_run.return_value = MagicMock(
        stdout="RUNNING gpu-node-01\n",
        returncode=0,
    )

    info = lifecycle_manager._get_job_info("12345")

    assert info is not None
    assert info["state"] == "RUNNING"
    assert info["node"] == "gpu-node-01"


@patch("tequila_mule.lifecycle.subprocess.run")
def test_get_job_info_pending(mock_subprocess_run, lifecycle_manager):
    """Test job info for pending job (no node allocated yet)."""
    mock_subprocess_run.return_value = MagicMock(
        stdout="PENDING (null)\n",
        returncode=0,
    )

    info = lifecycle_manager._get_job_info("12345")

    assert info is not None
    assert info["state"] == "PENDING"
    assert info["node"] is None


@patch("tequila_mule.lifecycle.subprocess.run")
def test_get_job_info_not_found(mock_subprocess_run, lifecycle_manager):
    """Test job info when job no longer in queue."""
    mock_subprocess_run.return_value = MagicMock(
        stdout="",
        returncode=0,
    )

    info = lifecycle_manager._get_job_info("12345")

    assert info is None
