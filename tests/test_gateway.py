"""Tests for gateway."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tequila_mule.config import Config
from tequila_mule.gateway import Gateway


@pytest.fixture
def gateway(tmp_path):
    """Create gateway instance."""
    config = Config()
    config.paths.api_keys_file = str(tmp_path / "api_keys.json")
    return Gateway(config)


@pytest.fixture
def client(gateway):
    """Create test client."""
    return TestClient(gateway.app)


def test_health_endpoint(client):
    """Test gateway health check."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "backend" in data


def test_no_auth_by_default(client, gateway):
    """Test requests succeed when no API key configured."""
    gateway.current_backend = "http://fake-backend:50000"

    # Should not require auth (will fail on backend connection, not auth)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
    )
    # Should get 503 (backend unreachable), not 401 (auth failed)
    assert response.status_code == 503


def test_auth_required_when_enabled(gateway):
    """Test auth is enforced when API keys configured."""
    # Add a key
    test_key = gateway.keystore.add_key("test@example.com")
    gateway.current_backend = "http://fake-backend:50000"

    client = TestClient(gateway.app)

    # Without auth header
    response = client.post(
        "/v1/chat/completions",
        json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401

    # With wrong key
    response = client.post(
        "/v1/chat/completions",
        json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401

    # With correct key should get 503 (backend unreachable, not auth error)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {test_key}"},
    )
    assert response.status_code == 503


def test_503_when_no_backend(client):
    """Test 503 response when no backend available."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_backend_registration(gateway):
    """Test backend registration endpoint."""
    registration_data = {
        "job_id": "12345",
        "node": "gpu-node-01",
        "port": 50000,
    }

    from fastapi import Request

    # Create mock request
    class MockRequest:
        async def json(self):
            return registration_data

    result = await gateway._register_backend(MockRequest())

    assert result["status"] == "registered"
    assert gateway.current_backend == "http://gpu-node-01:50000"


@pytest.mark.asyncio
async def test_set_backend(gateway):
    """Test atomic backend switching."""
    await gateway.set_backend("http://node1:50000")
    assert gateway.current_backend == "http://node1:50000"

    await gateway.set_backend("http://node2:50000")
    assert gateway.current_backend == "http://node2:50000"
