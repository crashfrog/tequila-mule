"""FastAPI gateway with OpenAI-compatible endpoints."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from .config import Config
from .keystore import KeyStore

logger = logging.getLogger(__name__)


class Gateway:
    """OpenAI-compatible gateway proxy."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.app = FastAPI(title="tequila-mule", version="0.1.0")
        self.current_backend: Optional[str] = None  # "http://node:port"
        self.backend_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=300.0)  # 5min for long completions

        # Load keystore
        keystore_path = Path(config.paths.api_keys_file).expanduser()
        self.keystore = KeyStore(keystore_path)

        # Register routes
        self.app.post("/v1/chat/completions")(self._chat_completions)
        self.app.post("/v1/completions")(self._completions)
        self.app.get("/v1/models")(self._models)
        self.app.post("/internal/register")(self._register_backend)
        self.app.get("/health")(self._health)

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
        """Proxy request to current backend."""
        await self._check_auth(request)

        if not self.current_backend:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No backend available",
                headers={"Retry-After": "60"},
            )

        url = f"{self.current_backend}{endpoint}"
        body = await request.body()

        try:
            if stream:
                # Stream response from backend
                async def stream_response():
                    async with self.client.stream(
                        "POST",
                        url,
                        content=body,
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk

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
        return await self._proxy_request(request, "/v1/chat/completions", stream=stream)

    async def _completions(self, request: Request) -> Response:
        """OpenAI completions endpoint."""
        body = await request.json()
        stream = body.get("stream", False)
        return await self._proxy_request(request, "/v1/completions", stream=stream)

    async def _models(self, request: Request) -> Response:
        """OpenAI models endpoint."""
        await self._check_auth(request)

        if not self.current_backend:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No backend available",
            )

        try:
            resp = await self.client.get(f"{self.current_backend}/v1/models")
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json",
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Backend unreachable",
            )

    async def _register_backend(self, request: Request) -> dict:
        """Internal endpoint for backends to register themselves."""
        data = await request.json()
        job_id = data["job_id"]
        node = data["node"]
        port = data["port"]

        backend_url = f"http://{node}:{port}"

        async with self.backend_lock:
            logger.info(f"Backend registered: {backend_url} (job {job_id})")
            self.current_backend = backend_url

        return {"status": "registered", "backend": backend_url}

    async def _health(self) -> dict:
        """Gateway health check."""
        return {
            "status": "healthy",
            "backend": self.current_backend if self.current_backend else "none",
        }

    async def set_backend(self, backend_url: str) -> None:
        """Set current backend (used by lifecycle manager)."""
        async with self.backend_lock:
            logger.info(f"Switching backend to: {backend_url}")
            self.current_backend = backend_url

    async def shutdown(self) -> None:
        """Shutdown gateway."""
        await self.client.aclose()
