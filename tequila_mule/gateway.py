"""FastAPI gateway with OpenAI-compatible endpoints."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from .config import Config
from .keystore import KeyStore

logger = logging.getLogger(__name__)

_UNSUPPORTED = {"tools", "tool_choice", "store", "parallel_tool_calls", "stream_options"}


@dataclass
class BackendEntry:
    """A live, registered backend for one configured backend pool."""

    url: str  # "http://node:port"
    model_name: str
    job_id: str


class Gateway:
    """OpenAI-compatible gateway proxy, routing across multiple backend pools."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.app = FastAPI(title="tequila-mule", version="0.1.0")
        self.backends: Dict[str, BackendEntry] = {}  # keyed by backend pool name
        self.backend_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=300.0)  # 5min for long completions

        # Static routing table: canonical backend name, model name, and every
        # alias all resolve to the owning backend pool's name.
        self._route_table: Dict[str, str] = self._build_route_table(config)

        # Load keystore
        keystore_path = Path(config.paths.api_keys_file).expanduser()
        self.keystore = KeyStore(keystore_path)

        # Register routes
        self.app.post("/v1/chat/completions")(self._chat_completions)
        self.app.post("/v1/completions")(self._completions)
        self.app.get("/v1/models")(self._models)
        self.app.post("/internal/register")(self._register_backend)
        self.app.get("/health")(self._health)

    @staticmethod
    def _build_route_table(config: Config) -> Dict[str, str]:
        table: Dict[str, str] = {}
        for backend in config.backends:
            table[backend.name] = backend.name
            table[backend.model.name] = backend.name
            for alias in backend.aliases:
                table[alias] = backend.name
        return table

    def get_backend(self, backend_name: str) -> Optional[str]:
        """Return the URL currently registered for a backend pool, if any."""
        entry = self.backends.get(backend_name)
        return entry.url if entry else None

    async def set_backend(
        self, backend_name: str, backend_url: str, model_name: str = "", job_id: str = ""
    ) -> None:
        """Set the live backend for a pool (used by the lifecycle manager)."""
        async with self.backend_lock:
            logger.info(f"[{backend_name}] Switching backend to: {backend_url}")
            self.backends[backend_name] = BackendEntry(
                url=backend_url, model_name=model_name, job_id=job_id
            )

    async def _check_auth(self, request: Request) -> Optional[str]:
        """Check API key if auth enabled. Returns email if authenticated."""
        if not self.keystore.has_keys():
            return None  # Auth disabled (no keys configured)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        token = auth_header[7:]  # Strip "Bearer "
        email = self.keystore.verify_key(token)
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        return email

    async def _proxy_request(
        self, request: Request, endpoint: str, stream: bool = False
    ) -> Response:
        """Resolve the target backend by model/alias and proxy the request."""
        await self._check_auth(request)

        try:
            body_json = json.loads(await request.body())
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

        requested_model = body_json.get("model")
        backend_name = self._route_table.get(requested_model) if requested_model else None
        if backend_name is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown model: {requested_model!r}",
            )

        entry = self.backends.get(backend_name)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Backend for model {requested_model!r} not ready",
                headers={"Retry-After": "60"},
            )

        url = f"{entry.url}{endpoint}"
        # Rewrite the model field to the backend's actual served model name so
        # clients can use a canonical name or alias. Also strip fields vLLM
        # 0.4.x doesn't support (tools, tool_choice, store, etc.) to avoid
        # 400 validation errors.
        body_json["model"] = entry.model_name
        for key in _UNSUPPORTED:
            body_json.pop(key, None)
        body = json.dumps(body_json).encode()

        try:
            if stream:
                # Stream response from backend, normalizing SSE chunks to
                # match the OpenAI spec: the final chunk must have an empty
                # delta ({}) with finish_reason set, not delta={"content":""}.
                # If the backend returns a non-2xx status, forward it as JSON
                # (headers not yet sent at that point so we can still do this).
                async def stream_response():
                    async with self.client.stream(
                        "POST",
                        url,
                        content=body,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status_code >= 400:
                            error_body = await resp.aread()
                            logger.error(f"Backend stream error {resp.status_code}: {error_body[:200]}")
                            # Emit a terminal SSE error so the client gets a
                            # meaningful failure instead of an empty stream.
                            err = json.dumps({"error": {"message": error_body.decode(errors="replace"), "type": "backend_error", "code": resp.status_code}})
                            yield b"data: " + err.encode() + b"\n\n"
                            yield b"data: [DONE]\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if not line:
                                continue  # skip blank separator lines
                            if not line.startswith("data: "):
                                continue  # skip other fields (event:, id:, etc.)
                            payload = line[6:]
                            if payload == "[DONE]":
                                yield b"data: [DONE]\n\n"
                                continue
                            try:
                                chunk = json.loads(payload)
                                for choice in chunk.get("choices", []):
                                    delta = choice.get("delta", {})
                                    # vLLM 0.4.x bundles content="" with
                                    # finish_reason in the last chunk; OpenAI
                                    # spec wants delta={} for that event.
                                    if choice.get("finish_reason") and delta.get("content") == "":
                                        choice["delta"] = {}
                                chunk.pop("usage", None)
                                yield b"data: " + json.dumps(chunk).encode() + b"\n\n"
                            except (json.JSONDecodeError, KeyError):
                                yield b"data: " + payload.encode() + b"\n\n"

                return StreamingResponse(
                    stream_response(),
                    media_type="text/event-stream",
                )
            else:
                resp = await self.client.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type="application/json",
                )

        except httpx.RequestError as e:
            logger.error(f"Backend request failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Backend unreachable",
            )

    async def _chat_completions(self, request: Request) -> Response:
        """OpenAI chat completions endpoint."""
        body = await request.json()
        stream = body.get("stream", False)
        logger.info(f"chat/completions: stream={stream} model={body.get('model')} messages={len(body.get('messages', []))}")
        return await self._proxy_request(request, "/v1/chat/completions", stream=stream)

    async def _completions(self, request: Request) -> Response:
        """OpenAI completions endpoint."""
        body = await request.json()
        stream = body.get("stream", False)
        return await self._proxy_request(request, "/v1/completions", stream=stream)

    async def _models(self, request: Request) -> Response:
        """OpenAI models endpoint. Lists canonical model names and aliases
        for every currently-registered (live) backend."""
        await self._check_auth(request)

        created = int(time.time())

        def model_obj(model_id: str, root: str) -> dict:
            # Full OpenAI-compatible model object. Some harnesses validate
            # strictly against this schema, so we populate every standard field
            # (created/owned_by/root/parent/permission) rather than the bare
            # id/object pair. `root` links an alias back to the served model.
            return {
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "tequila-mule",
                "root": root,
                "parent": None if model_id == root else root,
                "permission": [
                    {
                        "id": f"modelperm-{model_id}",
                        "object": "model_permission",
                        "created": created,
                        "allow_create_engine": False,
                        "allow_sampling": True,
                        "allow_logprobs": True,
                        "allow_search_indices": False,
                        "allow_view": True,
                        "allow_fine_tuning": False,
                        "organization": "*",
                        "group": None,
                        "is_blocking": False,
                    }
                ],
            }

        data = []
        for backend in self.config.backends:
            entry = self.backends.get(backend.name)
            if not entry:
                continue  # pool has no live job yet; don't advertise it
            data.append(model_obj(entry.model_name, entry.model_name))
            for alias in backend.aliases:
                data.append(model_obj(alias, entry.model_name))

        if not data:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No backend available",
            )

        return Response(
            content=json.dumps({"object": "list", "data": data}),
            media_type="application/json",
        )

    async def _register_backend(self, request: Request) -> dict:
        """Internal endpoint for backends to register themselves."""
        data = await request.json()
        job_id = data["job_id"]
        node = data["node"]
        port = data["port"]
        backend_name = data.get("backend_name")
        model_name = data.get("model_name", "")

        valid_names = {b.name for b in self.config.backends}
        if backend_name not in valid_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown backend_name: {backend_name!r}",
            )

        backend_url = f"http://{node}:{port}"
        await self.set_backend(backend_name, backend_url, model_name=model_name, job_id=job_id)

        return {"status": "registered", "backend": backend_url, "backend_name": backend_name}

    async def _health(self) -> dict:
        """Gateway health check."""
        return {
            "status": "healthy",
            "backends": {name: entry.url for name, entry in self.backends.items()},
        }

    async def shutdown(self) -> None:
        """Shutdown gateway."""
        await self.client.aclose()
