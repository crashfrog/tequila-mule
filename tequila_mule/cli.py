"""Command-line interface."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click
import uvicorn

from .config import Config, load_config
from .gateway import Gateway
from .health import HealthMonitor
from .keystore import KeyStore
from .lifecycle import LifecycleManager

logger = logging.getLogger(__name__)


class GatewayServer:
    """Main gateway server coordinator."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.gateway = Gateway(config)
        self.health_monitor = HealthMonitor()
        self.lifecycle_manager = LifecycleManager(config, self.gateway)

        # Wire up health monitor callback
        self.health_monitor.set_unhealthy_callback(self._on_backend_unhealthy)

    async def _on_backend_unhealthy(self) -> None:
        """Callback when backend becomes unhealthy."""
        logger.warning("Backend unhealthy, lifecycle manager will handle rotation")
        # Lifecycle manager will detect and rotate on next check

    async def start(self) -> None:
        """Start all components."""
        # Start lifecycle manager (handles cold start)
        await self.lifecycle_manager.start()

        # Start health monitor
        await self.health_monitor.start()

    async def stop(self) -> None:
        """Stop all components."""
        await self.lifecycle_manager.stop()
        await self.health_monitor.stop()
        await self.gateway.shutdown()


def run_server(config: Config) -> None:
    """Run the gateway server."""
    # Setup logging
    log_dir = Path(config.paths.log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "gateway.log"),
            logging.StreamHandler(),
        ],
    )

    # Create server
    server = GatewayServer(config)

    # Setup startup/shutdown hooks
    @server.gateway.app.on_event("startup")
    async def startup():
        await server.start()

    @server.gateway.app.on_event("shutdown")
    async def shutdown():
        await server.stop()

    # Run uvicorn
    uvicorn.run(
        server.gateway.app,
        host=config.gateway.host,
        port=config.gateway.port,
        log_level="info",
    )


@click.group()
@click.option("--config", type=click.Path(exists=True), help="Config file path")
@click.pass_context
def main(ctx: click.Context, config: Optional[str]) -> None:
    """tequila-mule: OpenAI-compatible gateway for Slurm-scheduled vLLM."""
    config_path = Path(config) if config else None
    ctx.obj = load_config(config_path)


@main.command()
@click.pass_obj
def start(config: Config) -> None:
    """Start the gateway server."""
    click.echo("Starting tequila-mule gateway...")
    click.echo(f"Gateway: {config.gateway.host}:{config.gateway.port}")
    click.echo(f"Model: {config.model.name}")
    click.echo(f"Partition: {config.slurm.partition}")

    # Check if auth enabled
    keystore_path = Path(config.paths.api_keys_file).expanduser()
    keystore = KeyStore(keystore_path)
    if keystore.has_keys():
        click.echo(f"Auth: ENABLED ({len(keystore.list_keys())} keys)")
    else:
        click.echo("Auth: DISABLED (run 'tequila-mule add-key <email>' to enable)")

    run_server(config)


@main.command()
@click.pass_obj
def status(config: Config) -> None:
    """Show current status."""
    state_file = Path(config.paths.state_file).expanduser()

    if not state_file.exists():
        click.echo("No state file found. Gateway may not be running.")
        return

    import json

    with open(state_file) as f:
        state = json.load(f)

    click.echo("=== tequila-mule Status ===")
    click.echo(f"Updated: {state.get('updated_at', 'unknown')}")
    click.echo()

    current = state.get("current_job")
    if current:
        click.echo("Current Job:")
        click.echo(f"  Job ID: {current['job_id']}")
        click.echo(f"  Node: {current.get('node', 'unknown')}")
        click.echo(f"  Status: {current['status']}")
        click.echo(f"  Expires: {current['expires_at']}")
    else:
        click.echo("Current Job: None")

    click.echo()

    pending = state.get("pending_job")
    if pending:
        click.echo("Pending Job:")
        click.echo(f"  Job ID: {pending['job_id']}")
        click.echo(f"  Status: {pending['status']}")
        click.echo(f"  Submitted: {pending['submitted_at']}")
    else:
        click.echo("Pending Job: None")


@main.command()
@click.pass_obj
def stop(config: Config) -> None:
    """Stop the gateway server."""
    click.echo("Stopping tequila-mule...")
    click.echo("(Use Ctrl+C in the terminal running 'tequila-mule start')")
    # TODO: Implement graceful shutdown via signal or PID file


@main.command()
@click.argument("email")
@click.pass_obj
def add_key(config: Config, email: str) -> None:
    """Add new API key for an email address."""
    keystore_path = Path(config.paths.api_keys_file).expanduser()
    keystore = KeyStore(keystore_path)

    try:
        new_key = keystore.add_key(email)
        click.echo(f"Created new API key for {email}:")
        click.echo(f"  {new_key}")
        click.echo()
        click.echo("Set in clients:")
        click.echo(f'  export OPENAI_API_KEY="{new_key}"')
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.pass_obj
def list_keys(config: Config) -> None:
    """List all API keys."""
    keystore_path = Path(config.paths.api_keys_file).expanduser()
    keystore = KeyStore(keystore_path)

    keys = keystore.list_keys()
    if not keys:
        click.echo("No API keys configured.")
        click.echo("Run 'tequila-mule add-key <email>' to create one.")
        return

    click.echo(f"API Keys ({len(keys)} total):")
    click.echo()
    for key_info in keys:
        click.echo(f"Email: {key_info['email']}")
        click.echo(f"  Key: {key_info['key']}")
        click.echo(f"  Created: {key_info['created_at']}")
        if key_info['last_used']:
            click.echo(f"  Last used: {key_info['last_used']}")
        else:
            click.echo("  Last used: never")
        click.echo()


@main.command()
@click.argument("key_or_email")
@click.pass_obj
def revoke_key(config: Config, key_or_email: str) -> None:
    """Revoke API key by key string or email address."""
    keystore_path = Path(config.paths.api_keys_file).expanduser()
    keystore = KeyStore(keystore_path)

    if keystore.revoke_key(key_or_email):
        click.echo(f"Revoked API key for: {key_or_email}")
    else:
        click.echo(f"No API key found for: {key_or_email}", err=True)
        sys.exit(1)


@main.command()
@click.argument("email", required=False)
@click.pass_obj
def show_key(config: Config, email: Optional[str]) -> None:
    """Show API key(s). If email provided, show that key; otherwise show all."""
    keystore_path = Path(config.paths.api_keys_file).expanduser()
    keystore = KeyStore(keystore_path)

    if email:
        key = keystore.get_key_by_email(email)
        if key:
            click.echo(f"API key for {email}:")
            click.echo(f"  {key}")
        else:
            click.echo(f"No API key found for: {email}", err=True)
            sys.exit(1)
    else:
        keys = keystore.list_keys()
        if not keys:
            click.echo("No API keys configured.")
            return

        click.echo("API Keys:")
        for key_info in keys:
            click.echo(f"{key_info['email']}: {key_info['key']}")


if __name__ == "__main__":
    main()
