"""Tests for gateway."""

import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse

from tequila_mule.config import Config
from tequila_mule.gateway import BackendEntry, Gateway


@pytest.fixture
def gateway(tmp_path):
    """Create gateway instance (single legacy "default" backend)."""
    config = Config()
    config.paths.api_keys_file = str(tmp_path / "api_keys.json")
    return Gateway(config)


@pytest.fixture
def multi_gateway(tmp_path, sample_multi_backend_config_data):
    """Create gateway instance with two backend pools and aliases."""
    data = dict(sample_multi_backend_config_data)
    data["paths"] = dict(data["paths"])
    data["paths"]["api_keys_file"] = str(tmp_path / "api_keys.json")
    config = Config(**data)
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
    assert "backends" in data


def test_no_auth_by_default(client, gateway):
    """Test requests succeed when no API key configured."""
    gateway.backends["default"] = BackendEntry(
        url="http://fake-backend:50000", model_name="meta-llama/Llama-3.1-8B", job_id="1"
    )

    # Should not require auth (will fail on backend connection, not auth)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "meta-llama/Llama-3.1-8B", "messages": [{"role": "user", "content": "hi"}]},
    )
    # Should get 503 (backend unreachable), not 401 (auth failed)
    assert response.status_code == 503


def test_auth_required_when_enabled(gateway):
    """Test auth is enforced when API keys configured."""
    # Add a key
    test_key = gateway.keystore.add_key("test@example.com")
    gateway.backends["default"] = BackendEntry(
        url="http://fake-backend:50000", model_name="meta-llama/Llama-3.1-8B", job_id="1"
    )

    client = TestClient(gateway.app)

    payload = {"model": "meta-llama/Llama-3.1-8B", "messages": [{"role": "user", "content": "hi"}]}

    # Without auth header
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401

    # With wrong key
    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401

    # With correct key should get 503 (backend unreachable, not auth error)
    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {test_key}"},
    )
    assert response.status_code == 503


def test_503_when_no_backend(client):
    """Test 503 response when no backend is registered for a valid model."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "meta-llama/Llama-3.1-8B", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    assert "Retry-After" in response.headers


def test_400_when_unknown_model(client):
    """Unknown model name/alias should 400, not silently fall back."""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "totally-unknown-model", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_backend_registration(gateway):
    """Test backend registration endpoint."""
    registration_data = {
        "job_id": "12345",
        "node": "gpu-node-01",
        "port": 50000,
        "backend_name": "default",
        "model_name": "meta-llama/Llama-3.1-8B",
    }

    class MockRequest:
        async def json(self):
            return registration_data

    result = await gateway._register_backend(MockRequest())

    assert result["status"] == "registered"
    assert gateway.get_backend("default") == "http://gpu-node-01:50000"


@pytest.mark.asyncio
async def test_backend_registration_unknown_name_rejected(gateway):
    """Registration with a backend_name not in config should 400."""
    from fastapi import HTTPException

    registration_data = {
        "job_id": "12345",
        "node": "gpu-node-01",
        "port": 50000,
        "backend_name": "not-a-real-backend",
    }

    class MockRequest:
        async def json(self):
            return registration_data

    with pytest.raises(HTTPException) as exc_info:
        await gateway._register_backend(MockRequest())
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_set_backend(gateway):
    """Test atomic backend switching."""
    await gateway.set_backend("default", "http://node1:50000")
    assert gateway.get_backend("default") == "http://node1:50000"

    await gateway.set_backend("default", "http://node2:50000")
    assert gateway.get_backend("default") == "http://node2:50000"


@pytest.mark.asyncio
async def test_route_by_canonical_model_name(multi_gateway):
    """Requests naming the exact model id route to the owning backend."""
    await multi_gateway.set_backend(
        "llama-3.3-70b", "http://llama-node:50000", model_name="meta-llama/Llama-3.3-70B-Instruct"
    )
    await multi_gateway.set_backend(
        "small-model-a", "http://small-node:50001", model_name="Qwen2.5-Coder-7B-Instruct"
    )

    client = TestClient(multi_gateway.app)

    with respx.mock:
        route = respx.post("http://small-node:50001/v1/chat/completions").mock(
            return_value=HttpxResponse(200, json={"id": "resp-1", "choices": []})
        )
        response = client.post(
            "/v1/chat/completions",
            json={"model": "Qwen2.5-Coder-7B-Instruct", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert route.called
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["model"] == "Qwen2.5-Coder-7B-Instruct"


@pytest.mark.asyncio
async def test_route_by_alias(multi_gateway):
    """Requests naming an alias route to the backend that owns it, with the
    outgoing model field rewritten to the backend's real model name."""
    await multi_gateway.set_backend(
        "llama-3.3-70b", "http://llama-node:50000", model_name="meta-llama/Llama-3.3-70B-Instruct"
    )
    await multi_gateway.set_backend(
        "small-model-a", "http://small-node:50001", model_name="Qwen2.5-Coder-7B-Instruct"
    )

    client = TestClient(multi_gateway.app)

    with respx.mock:
        route = respx.post("http://small-node:50001/v1/chat/completions").mock(
            return_value=HttpxResponse(200, json={"id": "resp-1", "choices": []})
        )
        response = client.post(
            "/v1/chat/completions",
            json={"model": "small", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert route.called
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["model"] == "Qwen2.5-Coder-7B-Instruct"


@pytest.mark.asyncio
async def test_models_endpoint_lists_aliases(multi_gateway):
    """/v1/models should list canonical ids and aliases for live backends only."""
    await multi_gateway.set_backend(
        "llama-3.3-70b", "http://llama-node:50000", model_name="meta-llama/Llama-3.3-70B-Instruct"
    )
    # small-model-a intentionally left unregistered (not yet live)

    client = TestClient(multi_gateway.app)
    response = client.get("/v1/models")

    assert response.status_code == 200
    ids = {entry["id"] for entry in response.json()["data"]}
    assert "meta-llama/Llama-3.3-70B-Instruct" in ids
    assert "llama" in ids
    assert "default" in ids
    # not live yet, must not be advertised
    assert "small" not in ids
    assert "Qwen2.5-Coder-7B-Instruct" not in ids
