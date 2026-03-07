from __future__ import annotations

import sys
from pathlib import Path

from genoflow.models.config import ToolConfig
from genoflow.runners.base import BaseRunner


class DockerToolRunner(BaseRunner):
    """
    Runs tools inside Docker containers (e.g. Bakta, PGAP).
    Uses the Docker Python SDK to pull images, mount volumes, and stream logs.
    Swapping Bakta for PGAP is purely a config change — this class handles both.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path):
        super().__init__(tool_config, output_dir)
        self.client = self._connect_to_docker()

    def _connect_to_docker(self):
        try:
            import docker
            client = docker.from_env()
            client.ping()           # actually test the connection
            return client
        except ImportError:
            raise RuntimeError(
                "The 'docker' Python package is not installed.\n"
                "Run: pip install docker"
            )
        except Exception:
            raise RuntimeError(
                "Cannot connect to Docker. Is Docker Desktop running?\n"
                "Start Docker Desktop and try again."
            )

    def preflight(self) -> None:
        print(f"\n[preflight] Checking docker tool: {self.config.name}")

        # 1. Check database path exists if tool requires one
        if self.config.database:
            db_path = self.config.database.path
            if not db_path.exists():
                raise RuntimeError(
                    f"  ✗  Database for {self.config.name} not found at: {db_path}\n"
                    f"     For Bakta, run:\n"
                    f"     bakta_db download --output {db_path} --type {self.config.database.type}"
                )
            print(f"  ✓  Database found at: {db_path}")

        # 2. Pull image if not already present, warn on version mismatch
        image_ref = self.config.image
        print(f"  Checking Docker image: {image_ref}")
        self._ensure_image(image_ref)

    def _ensure_image(self, image_ref: str) -> None:
        """Pull the image if it's not already present locally."""
        import docker
        try:
            image = self.client.images.get(image_ref)
            # try to extract a version label for the version check
            labels = image.labels or {}
            installed_version = labels.get("version", labels.get("org.opencontainers.image.version", "unknown"))
            if installed_version != "unknown":
                self._check_version(installed_version)
            else:
                print(f"  ✓  Image {image_ref} found locally.")
        except docker.errors.ImageNotFound:
            print(f"  Image {image_ref} not found locally. Pulling now (this may take a while)...")
            self._pull_image(image_ref)

    def _pull_image(self, image_ref: str) -> None:
        """Pull image with a simple progress indicator."""
        # split name and tag
        if ":" in image_ref:
            repo, tag = image_ref.rsplit(":", 1)
        else:
            repo, tag = image_ref, "latest"

        seen_layers = set()
        for line in self.client.api.pull(repo, tag=tag, stream=True, decode=True):
            layer_id = line.get("id", "")
            status = line.get("status", "")
            # only print each layer's first status line to avoid wall of text
            if layer_id and layer_id not in seen_layers:
                seen_layers.add(layer_id)
                print(f"  [{layer_id}] {status}")
            elif not layer_id and status:
                print(f"  {status}")

        print(f"  ✓  Image {image_ref} pulled successfully.")

    def run(self, fasta: Path) -> Path:
        """Mount volumes and run the Docker container."""
        print(f"\n[{self.config.name}] Starting annotation inside Docker...")

        volumes = self._build_volumes(fasta)
        cmd = self._build_command(fasta)
        log_file = self.log_dir / f"{self.config.name}.log"

        print(f"[{self.config.name}] Image:   {self.config.image}")
        print(f"[{self.config.name}] Command: {cmd}")
        print(f"[{self.config.name}] Logging to: {log_file}")

        with open(log_file, "w") as log:
            container = self.client.containers.run(
                self.config.image,
                command=cmd,
                volumes=volumes,
                remove=True,            # delete container after it exits
                detach=False,           # wait for completion
                stdout=True,
                stderr=True,
            )
            # container output is bytes when detach=False
            output = container if isinstance(container, bytes) else b""
            log.write(output.decode("utf-8", errors="replace"))

        print(f"[{self.config.name}] ✓ Finished. Output at: {self.output_dir}")
        return self.output_dir

    def _build_volumes(self, fasta: Path) -> dict:
        """
        Map host paths → container paths.
        Standard convention: /input, /output, /db inside every container.
        """
        volumes = {
            str(fasta.parent.resolve()): {"bind": "/input",  "mode": "ro"},
            str(self.output_dir.resolve()): {"bind": "/output", "mode": "rw"},
        }
        if self.config.database:
            volumes[str(self.config.database.path)] = {"bind": "/db", "mode": "ro"}
        return volumes

    def _build_command(self, fasta: Path) -> str:
        """Build the container command string for this specific tool."""
        if self.config.name == "bakta":
            return self._bakta_command(fasta)
        if self.config.name == "pgap":
            return self._pgap_command(fasta)

        # generic fallback
        return f"--input /input/{fasta.name} --output /output"

    def _bakta_command(self, fasta: Path) -> str:
        # The Bakta image uses bakta itself as the entrypoint, so we pass
        # arguments directly — no 'bakta' prefix. Genome is positional and must come first.
        cmd = f"/input/{fasta.name} --db /db --output /output --force"
        for key, val in self.config.params.items():
            cmd += f" --{key} {val}"
        return cmd

    def _pgap_command(self, fasta: Path) -> str:
        # PGAP has a different invocation — placeholder for when you swap in PGAP later
        cmd = (
            f"--fasta /input/{fasta.name} "
            f"--output /output "
            f"--database /db"
        )
        for key, val in self.config.params.items():
            cmd += f" --{key} {val}"
        return cmd
