"""
bactowise/utils/db_manager.py

Manages downloads of all databases required by the BactoWise pipeline.

Default storage location: ~/.bactowise/databases/
  ~/.bactowise/databases/checkm/   — CheckM marker gene database (~2 GB)
  ~/.bactowise/databases/bakta/    — Bakta annotation database, light build (~2 GB)

Usage (from CLI):
    bactowise db download              # download both databases
    bactowise db download --checkm     # CheckM only
    bactowise db download --bakta      # Bakta only
    bactowise db download --force-db-download   # re-download even if present
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

# ── Default paths ─────────────────────────────────────────────────────────────

DEFAULT_DB_ROOT = Path("~/.bactowise/databases").expanduser()

CHECKM_DB_URL = (
    "https://data.ace.uq.edu.au/public/CheckM_databases/"
    "checkm_data_2015_01_16.tar.gz"
)

# Markers that confirm a completed download for each database.
# We check for these rather than just a non-empty directory to guard against
# partial downloads left behind by a previous interrupted run.
#
# CheckM: the tarball extracts several top-level directories; we confirm
# two that are always present — genome_tree/ and hmms/ — using both to
# reduce the chance of a false positive from a partial extraction.
_CHECKM_MARKERS = ["genome_tree", "hmms", "pfam"]

# Bakta: bakta_db creates a db-light/ subdir inside --output; the database
# itself is confirmed by the presence of bakta.db inside db-light/.
_BAKTA_SUBDIR    = "db-light"
_BAKTA_MARKER    = "bakta.db"




# ── Public helpers ─────────────────────────────────────────────────────────────

def checkm_db_path(db_root: Path = DEFAULT_DB_ROOT) -> Path:
    return db_root / "checkm"


def bakta_db_path(db_root: Path = DEFAULT_DB_ROOT) -> Path:
    """Returns the actual Bakta database directory (bakta/db-light/).
    This is what gets mounted into Docker and passed to the tool."""
    return db_root / "bakta" / _BAKTA_SUBDIR


def is_checkm_present(db_root: Path = DEFAULT_DB_ROOT) -> bool:
    """Return True only if the CheckM database appears complete.
    Checks that all expected top-level directories exist inside the db path."""
    db = checkm_db_path(db_root)
    return all((db / marker).is_dir() for marker in _CHECKM_MARKERS)


def is_bakta_present(db_root: Path = DEFAULT_DB_ROOT) -> bool:
    """Return True only if the Bakta database appears complete.
    Checks for db.json inside the db-light/ subdirectory."""
    return (bakta_db_path(db_root) / _BAKTA_MARKER).exists()


# ── Download orchestration ─────────────────────────────────────────────────────

def download_all(
    force: bool = False,
    db_root: Path = DEFAULT_DB_ROOT,
    checkm: bool = True,
    bakta: bool = True,
) -> None:
    """Download CheckM and/or Bakta databases.

    Parameters
    ----------
    force   : re-download even if already present
    db_root : parent directory for all BactoWise databases
    checkm  : whether to download the CheckM database
    bakta   : whether to download the Bakta database
    """
    if checkm:
        download_checkm(force=force, db_root=db_root)
    if bakta:
        download_bakta(force=force, db_root=db_root)


def download_checkm(force: bool = False, db_root: Path = DEFAULT_DB_ROOT) -> Path:
    """
    Download and extract the CheckM marker gene database.

    The tarball is downloaded to a temporary file alongside the destination
    directory, then extracted in-place, and the tarball is deleted on success.

    Parameters
    ----------
    force   : re-download even if the database appears complete
    db_root : parent directory for all BactoWise databases
    """
    dest = checkm_db_path(db_root)

    if is_checkm_present(db_root) and not force:
        print(f"  ✓  CheckM database already present at: {dest}")
        print(f"     (use --force-db-download to re-download)")
        return dest

    if force and dest.exists():
        print(f"  Removing existing CheckM database at: {dest}")
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    tarball = dest / "checkm_data.tar.gz"

    print(f"\n  Downloading CheckM database (~2 GB) → {dest}")
    print(f"  Source: {CHECKM_DB_URL}")

    try:
        _download_with_progress(CHECKM_DB_URL, tarball)
    except Exception as e:
        tarball.unlink(missing_ok=True)
        raise RuntimeError(
            f"CheckM download failed: {e}\n"
            f"Check your network connection and try again."
        ) from e

    print(f"  Extracting archive…")
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(path=dest)
    except Exception as e:
        raise RuntimeError(f"Failed to extract CheckM tarball: {e}") from e
    finally:
        tarball.unlink(missing_ok=True)

    if not is_checkm_present(db_root):
        raise RuntimeError(
            f"CheckM database extraction appeared to succeed but the expected "
            f"marker file was not found inside {dest}.\n"
            f"The archive structure may have changed upstream. "
            f"Please report this at https://github.com/your-org/bactowise/issues"
        )

    print(f"  ✓  CheckM database ready at: {dest}\n")
    return dest


def download_bakta(force: bool = False, db_root: Path = DEFAULT_DB_ROOT) -> Path:
    """
    Download the Bakta light database using bakta_db.

    Since Bakta runs inside a Singularity container (not installed in the
    BactoWise conda environment), bakta_db is invoked in one of two ways:

    1. Via the Bakta Singularity SIF — preferred, and works even if bakta is
       not installed as a conda package.
    2. Via bakta_db on PATH — fallback for Docker-based setups where bakta
       is installed in the active conda environment.

    Parameters
    ----------
    force   : re-download even if the database appears complete
    db_root : parent directory for all BactoWise databases
    """
    dest_dir = db_root / "bakta"
    dest     = bakta_db_path(db_root)   # db-light/ inside dest_dir

    if is_bakta_present(db_root) and not force:
        print(f"  ✓  Bakta database already present at: {dest}")
        print(f"     (use --force-db-download to re-download)")
        return dest

    if force and dest_dir.exists():
        print(f"  Removing existing Bakta database at: {dest_dir}")
        shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    cmd = _bakta_db_download_cmd(dest_dir)

    print(f"\n  Downloading Bakta database (light, ~2 GB) → {dest}")
    print(f"  Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"bakta_db download failed (exit {result.returncode}).\n"
            f"Check the output above for details."
        )

    if not is_bakta_present(db_root):
        raise RuntimeError(
            f"Bakta download appeared to succeed but {_BAKTA_MARKER} was not "
            f"found inside {dest}.\n"
            f"The bakta_db output structure may have changed."
        )

    print(f"\n  ✓  Bakta database ready at: {dest}\n")
    return dest


def _bakta_db_download_cmd(dest_dir: Path) -> list[str]:
    """
    Build the command to run bakta_db download.

    Tries in order:
    1. Singularity/Apptainer + bakta SIF — pulls the SIF automatically if missing.
    2. Docker + bakta image — pulls the image automatically if missing.
    3. bakta_db on PATH — fallback for conda-based setups.

    Raises RuntimeError if none of the above are available.
    """
    # ── Option 1: Singularity/Apptainer ──────────────────────────────────────
    singularity_bin = shutil.which("singularity") or shutil.which("apptainer")
    if singularity_bin:
        sif = _bakta_sif_path()
        if not sif.exists():
            _pull_bakta_sif(singularity_bin, sif)
        print(f"  Using Singularity image: {sif}")
        return [
            singularity_bin, "run",
            "--bind", f"{dest_dir}:/db_output:rw",
            str(sif),
            "db", "--output", "/db_output", "--type", "light",
        ]

    # ── Option 2: Docker ─────────────────────────────────────────────────────
    if shutil.which("docker"):
        image_ref = _bakta_image_ref()
        _ensure_docker_image(image_ref)
        print(f"  Using Docker image: {image_ref}")
        return [
            "docker", "run", "--rm",
            "--volume", f"{dest_dir}:/db_output",
            image_ref,
            "db", "--output", "/db_output", "--type", "light",
        ]

    # ── Option 3: bakta_db on PATH ────────────────────────────────────────────
    if shutil.which("bakta_db"):
        return ["bakta_db", "download", "--output", str(dest_dir), "--type", "light"]

    # ── Nothing available ─────────────────────────────────────────────────────
    raise RuntimeError(
        "Cannot download Bakta database — no container runtime found.\n\n"
        "Option A (Singularity/Apptainer — recommended for HPC):\n"
        "  sudo add-apt-repository -y ppa:apptainer/ppa\n"
        "  sudo apt update && sudo apt install apptainer\n"
        "  bactowise db download --bakta\n\n"
        "Option B (Docker — for local workstations):\n"
        "  Install Docker Desktop from https://docker.com\n"
        "  bactowise db download --bakta\n\n"
        "Option C (conda):\n"
        "  conda install -c bioconda bakta\n"
        "  bactowise db download --bakta"
    )


def _bakta_image_ref() -> str:
    """
    Read the Bakta image reference from the bundled pipeline.yaml.

    This is the single source of truth for the Bakta version — updating
    bactowise/config/pipeline.yaml is the only change needed when bumping
    the Bakta version.
    """
    import yaml
    from bactowise.utils.config_manager import bundled_config_path
    config = yaml.safe_load(bundled_config_path().read_text())
    for tool in config.get("tools", []):
        if tool.get("name") == "bakta":
            image = tool.get("image")
            if image:
                return image
    raise RuntimeError(
        "Could not find bakta image reference in bundled pipeline.yaml. "
        "The bundled config may be malformed."
    )


def _pull_bakta_sif(singularity_bin: str, sif: Path) -> None:
    """
    Pull the Bakta Docker image as a SIF file.
    Called automatically by _bakta_db_download_cmd when the SIF is missing.
    """
    image_ref = _bakta_image_ref()
    uri       = f"docker://{image_ref}"

    sif.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n  Bakta SIF not found — pulling image first.")
    print(f"  Source : {uri}")
    print(f"  Dest   : {sif}")
    print(f"  This is a one-time step and may take several minutes.\n")

    result = subprocess.run(
        [singularity_bin, "pull", str(sif), uri],
        text=True,
    )

    if result.returncode != 0 or not sif.exists():
        sif.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to pull Bakta Singularity image.\n"
            f"Try manually: {singularity_bin} pull {sif} {uri}"
        )

    print(f"\n  ✓  Bakta SIF pulled: {sif}")


def _bakta_sif_path() -> Path:
    """
    Return the expected local path of the Bakta SIF file, derived from the
    image reference in the bundled pipeline.yaml.

    oschwengers/bakta:v1.12.0 → ~/.bactowise/images/oschwengers_bakta_v1.12.0.sif
    """
    safe_name = _bakta_image_ref().replace("/", "_").replace(":", "_")
    return Path("~/.bactowise/images").expanduser() / f"{safe_name}.sif"


def _ensure_docker_image(image_ref: str) -> None:
    """
    Pull the Bakta Docker image if it is not already present locally.
    """
    # Check if the image exists locally without making a network call
    check = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        print(f"  Docker image already present: {image_ref}")
        return

    print(f"\n  Bakta Docker image not found — pulling now.")
    print(f"  Image : {image_ref}")
    print(f"  This is a one-time step and may take several minutes.\n")

    result = subprocess.run(["docker", "pull", image_ref], text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to pull Bakta Docker image: {image_ref}\n"
            f"Make sure Docker is running and try again."
        )
    print(f"\n  ✓  Docker image pulled: {image_ref}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _download_with_progress(url: str, dest: Path) -> None:
    """
    Download a URL to dest with a simple terminal progress indicator.
    Uses only stdlib (urllib) — no extra dependencies.
    """
    def _reporthook(count: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            mb_done = count * block_size / 1024 / 1024
            print(f"\r  Downloaded {mb_done:.1f} MB…", end="", flush=True)
        else:
            pct      = min(count * block_size * 100 / total_size, 100)
            mb_done  = count * block_size / 1024 / 1024
            mb_total = total_size / 1024 / 1024
            bar_len  = 30
            filled   = int(bar_len * pct / 100)
            bar      = "█" * filled + "░" * (bar_len - filled)
            print(
                f"\r  [{bar}] {pct:5.1f}%  {mb_done:.0f}/{mb_total:.0f} MB",
                end="",
                flush=True,
            )

    urllib.request.urlretrieve(url, dest, reporthook=_reporthook)
    print()  # newline after progress bar finishes
