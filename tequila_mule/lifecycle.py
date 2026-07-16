"""Slurm job lifecycle management."""

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .config import BackendPoolConfig, PathsConfig

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    """State of a Slurm job."""

    job_id: str
    node: Optional[str]
    port: int
    status: str  # PENDING, RUNNING, COMPLETED, FAILED
    submitted_at: str
    expires_at: str
    backend_url: Optional[str] = None


def _parse_wall_time(wall_time: str) -> timedelta:
    """Parse wall_time (HH:MM:SS or D-HH:MM:SS) into a timedelta."""
    if "-" in wall_time:
        days_str, time_str = wall_time.split("-")
        days = int(days_str)
        h, m, s = map(int, time_str.split(":"))
        return timedelta(days=days, hours=h, minutes=m, seconds=s)

    h, m, s = map(int, wall_time.split(":"))
    return timedelta(hours=h, minutes=m, seconds=s)


class LifecycleManager:
    """Manage Slurm job submission and rotation for a single backend pool."""

    def __init__(
        self,
        backend_config: BackendPoolConfig,
        paths: PathsConfig,
        gateway_host: str,
        gateway_port: int,
        gateway: "Gateway",  # type: ignore
    ) -> None:
        self.name = backend_config.name
        self.backend_config = backend_config
        self.paths = paths
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.gateway = gateway
        self.current_job: Optional[JobState] = None
        self.pending_job: Optional[JobState] = None
        self.running = False
        self.task: Optional[asyncio.Task] = None

        # Setup Jinja2 for job template rendering
        template_dir = Path(paths.job_template).parent
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        self.template_name = Path(paths.job_template).name

        # Per-backend state file, e.g. ~/.tequila-mule/state-default.json
        self.state_file = Path(paths.state_file).expanduser().with_name(
            f"state-{self.name}.json"
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Legacy single-backend state file, used as a one-time migration
        # fallback so an in-place upgrade of an existing "default" backend
        # doesn't lose track of an already-running job.
        self._legacy_state_file = Path(paths.state_file).expanduser()

    def _load_state(self) -> None:
        """Load state from disk."""
        state_file = self.state_file
        if not state_file.exists():
            if self.name == "default" and self._legacy_state_file.exists():
                logger.info(
                    f"No {state_file} found; migrating legacy state from "
                    f"{self._legacy_state_file}"
                )
                state_file = self._legacy_state_file
            else:
                return

        try:
            with open(state_file) as f:
                data = json.load(f)

            if data.get("current_job"):
                self.current_job = JobState(**data["current_job"])
                logger.info(f"[{self.name}] Loaded current job: {self.current_job.job_id}")

            if data.get("pending_job"):
                self.pending_job = JobState(**data["pending_job"])
                logger.info(f"[{self.name}] Loaded pending job: {self.pending_job.job_id}")

        except Exception as e:
            logger.error(f"[{self.name}] Failed to load state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        try:
            data = {
                "current_job": asdict(self.current_job) if self.current_job else None,
                "pending_job": asdict(self.pending_job) if self.pending_job else None,
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Atomic write
            tmp_file = self.state_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)
            tmp_file.replace(self.state_file)

        except Exception as e:
            logger.error(f"[{self.name}] Failed to save state: {e}")

    def _submit_job(self) -> str:
        """Submit a new Slurm job. Returns job_id."""
        submitted_at = datetime.utcnow()
        duration = _parse_wall_time(self.backend_config.slurm.wall_time)
        expires_at = submitted_at + duration  # noqa: F841 (kept for parity/clarity)

        # Render job script
        template = self.jinja_env.get_template(self.template_name)
        script = template.render(
            partition=self.backend_config.slurm.partition,
            gres=self.backend_config.slurm.gres,
            wall_time=self.backend_config.slurm.wall_time,
            container_path=self.paths.container_path,
            model_name=self.backend_config.model.name,
            vllm_port=self.backend_config.slurm.port,
            vllm_extra_args=self.backend_config.model.vllm_extra_args,
            backend_name=self.name,
            gateway_host=self.gateway_host,
            gateway_port=self.gateway_port,
        )

        # Submit via sbatch
        logger.info(f"[{self.name}] Submitting Slurm job")
        result = subprocess.run(
            ["sbatch", "--parsable"],
            input=script.encode(),
            capture_output=True,
            check=True,
        )
        job_id = result.stdout.decode().strip()
        logger.info(f"[{self.name}] Job submitted: {job_id}")

        return job_id

    def _get_job_info(self, job_id: str) -> Optional[dict]:
        """Query squeue for job info."""
        try:
            result = subprocess.run(
                ["squeue", "-j", job_id, "-h", "-o", "%T %N"],
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            if not output:
                return None

            parts = output.split()
            return {
                "state": parts[0],  # PENDING, RUNNING, etc.
                "node": parts[1] if len(parts) > 1 and parts[1] != "(null)" else None,
            }
        except subprocess.CalledProcessError:
            return None

    async def start(self) -> None:
        """Start lifecycle manager."""
        self.running = True
        self._load_state()

        # Validate loaded state against squeue
        if self.current_job:
            info = self._get_job_info(self.current_job.job_id)
            if not info or info["state"] not in ("RUNNING", "PENDING"):
                logger.warning(
                    f"[{self.name}] Current job {self.current_job.job_id} no longer valid"
                )
                self.current_job = None
            elif self.current_job.backend_url:
                # Rehydrate the gateway's registry so a restart doesn't briefly
                # 503 requests for an already-running backend.
                await self.gateway.set_backend(
                    self.name,
                    self.current_job.backend_url,
                    model_name=self.backend_config.model.name,
                    job_id=self.current_job.job_id,
                )

        # Cold start: submit job immediately if no current job.
        # Run as a background task so uvicorn finishes startup and can
        # accept the /internal/register callback from the compute node.
        if not self.current_job:
            asyncio.create_task(self._cold_start())

        self.task = asyncio.create_task(self._rotation_loop())
        logger.info(f"[{self.name}] Lifecycle manager started")

    async def stop(self) -> None:
        """Stop lifecycle manager."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.name}] Lifecycle manager stopped")

    async def _cold_start(self) -> None:
        """Handle cold start - no current job."""
        logger.info(f"[{self.name}] Cold start: submitting initial job")

        job_id = self._submit_job()
        submitted_at = datetime.utcnow()
        duration = _parse_wall_time(self.backend_config.slurm.wall_time)
        expires_at = submitted_at + duration

        self.pending_job = JobState(
            job_id=job_id,
            node=None,
            port=self.backend_config.slurm.port,
            status="PENDING",
            submitted_at=submitted_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        self._save_state()

        # Wait for job to become current
        await self._wait_for_job_ready(self.pending_job)

    async def _wait_for_job_ready(self, job: JobState) -> None:
        """Wait for job to reach RUNNING and register with gateway."""
        logger.info(f"[{self.name}] Waiting for job {job.job_id} to become ready")

        # Poll until RUNNING
        while self.running:
            info = self._get_job_info(job.job_id)
            if not info:
                logger.error(f"[{self.name}] Job {job.job_id} disappeared from queue")
                job.status = "FAILED"
                self._save_state()
                return

            if info["state"] == "RUNNING":
                job.status = "RUNNING"
                job.node = info["node"]
                job.backend_url = f"http://{job.node}:{job.port}"
                logger.info(f"[{self.name}] Job {job.job_id} running on {job.node}")
                break

            await asyncio.sleep(5)

        # Job is running, wait for registration (up to 5 min)
        # Gateway's /internal/register will set the backend for this pool.
        start_time = datetime.utcnow()
        while self.running:
            if (datetime.utcnow() - start_time).total_seconds() > 300:
                logger.error(f"[{self.name}] Job {job.job_id} failed to register within 5 minutes")
                job.status = "FAILED"
                self._save_state()
                return

            # Check if gateway backend matches our job
            if self.gateway.get_backend(self.name) == job.backend_url:
                logger.info(f"[{self.name}] Job {job.job_id} registered successfully")

                # Promote pending → current
                self.current_job = job
                self.pending_job = None
                self._save_state()
                return

            await asyncio.sleep(2)

    async def _rotation_loop(self) -> None:
        """Main rotation loop."""
        while self.running:
            if not self.current_job:
                await asyncio.sleep(10)
                continue

            # Calculate time until rotation needed
            expires_at = datetime.fromisoformat(self.current_job.expires_at)
            lead_time = timedelta(minutes=self.backend_config.slurm.lead_time_minutes)
            rotation_time = expires_at - lead_time

            now = datetime.utcnow()
            if now >= rotation_time and not self.pending_job:
                # Submit next job
                logger.info(f"[{self.name}] Rotation window reached, submitting next job")

                job_id = self._submit_job()
                submitted_at = datetime.utcnow()
                duration = _parse_wall_time(self.backend_config.slurm.wall_time)
                expires_at_new = submitted_at + duration

                self.pending_job = JobState(
                    job_id=job_id,
                    node=None,
                    port=self.backend_config.slurm.port,
                    status="PENDING",
                    submitted_at=submitted_at.isoformat(),
                    expires_at=expires_at_new.isoformat(),
                )
                self._save_state()

                # Wait for pending job to be ready, then promote
                await self._wait_for_job_ready(self.pending_job)

            await asyncio.sleep(30)  # Check every 30s
