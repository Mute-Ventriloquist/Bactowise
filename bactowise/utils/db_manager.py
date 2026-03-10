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
# bakta_db creates a db-light/ subdirectory inside the --output path.
# The actual database root is therefore bakta/db-light/, and db.json
# lives inside that subdirectory.
_BAKTA_SUBDIR   = "db-light"
_BAKTA_MARKER   = "bakta.db"


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

def download_all(force: bool = False, db_root: Path = DEFAULT_DB_ROOT) -> None:
    """Download both CheckM and Bakta databases."""
    download_checkm(force=force, db_root=db_root)
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
    Download the Bakta light database using the `bakta_db` CLI tool.

    `bakta_db` is installed as a run dependency of bactowise (via meta.yaml)
    so it is always available on PATH when bactowise is active.

    Parameters
    ----------
    force   : re-download even if the database appears complete
    db_root : parent directory for all BactoWise databases
    """
    # dest_dir is the parent we pass to bakta_db --output.
    # bakta_db will create db-light/ inside it automatically.
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

    # Confirm bakta_db is available before attempting download
    if not shutil.which("bakta_db"):
        raise RuntimeError(
            "  ✗  'bakta_db' not found on PATH.\n"
            "     Make sure bactowise is installed in your active conda environment:\n"
            "       conda activate <your-bactowise-env>\n"
            "     Then retry: bactowise db download --bakta"
        )

    print(f"\n  Downloading Bakta database (light, ~2 GB) → {dest}")
    cmd = ["bakta_db", "download", "--output", str(dest_dir), "--type", "light"]
    print(f"  Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"  ✗  bakta_db download failed (exit {result.returncode}).\n"
            f"     Check the output above for details."
        )

    if not is_bakta_present(db_root):
        raise RuntimeError(
            f"  ✗  Bakta download appeared to succeed but the expected marker "
            f"file (db.json) was not found inside {dest}.\n"
            f"     The bakta_db output structure may have changed. "
            f"Please report this at https://github.com/your-org/bactowise/issues"
        )

    print(f"\n  ✓  Bakta database ready at: {dest}\n")
    return dest


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
