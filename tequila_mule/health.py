"""Backend health monitoring."""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Monitor backend health and trigger lifecycle checks on failure."""

    def __init__(self, backend_name: str, check_interval: int = 30) -> None:
        self.backend_name = backend_name
        self.check_interval = check_interval
        self.current_backend: Optional[str] = None
        self.is_healthy = True
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.on_unhealthy_callback: Optional[callable] = None

    def set_backend(self, backend_url: str) -> None:
        """Update backend to monitor."""
        self.current_backend = backend_url
        self.is_healthy = True
        logger.info(f"[{self.backend_name}] Health monitor tracking: {backend_url}")

    def set_unhealthy_callback(self, callback: callable) -> None:
        """Set callback to trigger on backend failure."""
        self.on_unhealthy_callback = callback

    async def start(self) -> None:
        """Start health monitoring loop."""
        self.running = True
        self.task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started")

    async def stop(self) -> None:
        """Stop health monitoring."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped")

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        consecutive_failures = 0

        while self.running:
            if self.current_backend:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(f"{self.current_backend}/health")
                        if resp.status_code == 200:
                            if not self.is_healthy:
                                logger.info(f"[{self.backend_name}] Backend recovered")
                            self.is_healthy = True
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            logger.warning(
                                f"[{self.backend_name}] Backend unhealthy: HTTP {resp.status_code} "
                                f"({consecutive_failures} consecutive)"
                            )

                except httpx.RequestError as e:
                    consecutive_failures += 1
                    logger.warning(
                        f"[{self.backend_name}] Backend unreachable: {e} "
                        f"({consecutive_failures} consecutive)"
                    )

                # Mark unhealthy after 3 consecutive failures
                if consecutive_failures >= 3 and self.is_healthy:
                    self.is_healthy = False
                    logger.error(f"[{self.backend_name}] Backend marked unhealthy")
                    if self.on_unhealthy_callback:
                        await self.on_unhealthy_callback()

            await asyncio.sleep(self.check_interval)
