"""
bactowise/utils/db_manager.py

Manages downloads of all databases required by the BactoWise pipeline.

Default storage location: ~/.bactowise/databases/
  ~/.bactowise/databases/checkm/   — CheckM marker gene database (~2 GB)
  ~/.bactowise/databases/bakta/    — Bakta annotation database, full build (~71 GB)
  ~/.bactowise/databases/pgap/     — PGAP supplemental data (~30 GB)

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

# Bakta: bakta_db creates a db-full/ subdir inside --output; the database
# itself is confirmed by the presence of bakta.db inside db-full/.
_BAKTA_SUBDIR    = "db-full"
_BAKTA_MARKER    = "bakta.db"

# PGAP: pgap.py --update downloads data to wherever PGAP_INPUT_DIR points.
# BactoWise sets PGAP_INPUT_DIR to ~/.bactowise/databases/pgap/ during download
# so it lives alongside the other managed databases. pgap.py creates a versioned
# input-VERSION.BUILD/ subdirectory inside this path.
_DEFAULT_PGAP_DATA_DIR = Path("~/.bactowise/databases/pgap").expanduser()
_PGAP_BIN_DIR          = Path("~/.bactowise/bin").expanduser()
_PGAP_WRAPPER_URL      = "https://github.com/ncbi/pgap/raw/prod/scripts/pgap.py"
_PGAP_DATA_MARKER      = "build_number"

# Phigaro: phigaro-setup writes a config.yml and the pVOG HMM profiles to
# ~/.bactowise/databases/phigaro/. BactoWise passes -c and -p to
# phigaro-setup to redirect the default ~/.phigaro/ location here.
# We check for the HMM file (written before config.yml) as the presence marker
# so a partial setup that already downloaded the database doesn't re-download.
_PHIGARO_DB_DIR    = Path("~/.bactowise/databases/phigaro").expanduser()
_PHIGARO_DB_MARKER = "config.yml"
_PHIGARO_HMM_FILE  = "allpvoghmms"  # downloaded before config.yml is written

# Platon: mandatory database downloaded from Zenodo to ~/.bactowise/databases/platon/db/
# Zipped ~1.6 GB, unzipped ~2.8 GB. BactoWise downloads and extracts automatically.
_PLATON_DB_DIR     = Path("~/.bactowise/databases/platon/db").expanduser()
_PLATON_DB_URL     = "https://zenodo.org/record/4066768/files/db.tar.gz"
_PLATON_DB_TARBALL = "db.tar.gz"

# EggNOG-mapper: downloaded via download_eggnog_data.py to a managed location.
# ~20 GB total: eggnog.db (~15 GB SQLite), eggnog_proteins.dmnd (~4 GB diamond DB),
# eggnog.taxa.db (taxonomy). BactoWise passes --data_dir to both the download
# script and emapper.py to keep everything under ~/.bactowise/databases/.
_EGGNOG_DB_DIR    = Path("~/.bactowise/databases/eggnog").expanduser()
_EGGNOG_DB_MARKER = "eggnog_proteins.dmnd"   # largest file, written last

# SPIFinder: Salmonella Pathogenicity Island finder (CGE tool).
# No Docker image or conda package exists — installed via git clone.
# Both the tool script and the database are cloned from Bitbucket into
# ~/.bactowise/databases/spifinder/ so everything is co-located.
_SPIFINDER_ROOT   = Path("~/.bactowise/databases/spifinder").expanduser()
_SPIFINDER_SCRIPT = _SPIFINDER_ROOT / "spifinder" / "spifinder.py"
_SPIFINDER_DB_DIR = _SPIFINDER_ROOT / "spifinder_db"
# The db contains several .fsa files (one per SPI). We glob for any of them
# rather than hardcoding a single filename so the check survives upstream
# renames without requiring a BactoWise update.
_SPIFINDER_DB_MARKER_GLOB = "*.fsa"

# AMRFinderPlus: amrfinder -u stores the database inside the conda environment
# at envs/amrfinderplus_env/share/amrfinderplus/data/. BactoWise cannot
# redirect this path (amrfinder -u has no --output flag), so it is detected
# by searching common conda root locations for the known marker file AMRProt.fa.
_AMRFINDERPLUS_ENV_NAME   = "amrfinderplus_env"
_AMRFINDERPLUS_DB_SUBPATH = Path("envs") / _AMRFINDERPLUS_ENV_NAME / "share" / "amrfinderplus" / "data"
# Database lives in a versioned subdir: data/YYYY-MM-DD.#/AMRProt
# We glob for AMRProt in any subdirectory under data/
_AMRFINDERPLUS_DB_MARKER  = "AMRProt"

# Common conda root locations to search when locating the amrfinderplus database
_CONDA_ROOT_CANDIDATES = [
    Path(p).expanduser() for p in [
        "~/miniconda3", "~/anaconda3", "~/mambaforge",
        "~/miniforge3", "/opt/conda", "/opt/miniconda3", "/opt/anaconda3",
    ]
]


# ── Public helpers ─────────────────────────────────────────────────────────────

def checkm_db_path(db_root: Path = DEFAULT_DB_ROOT) -> Path:
    return db_root / "checkm"


def bakta_db_path(db_root: Path = DEFAULT_DB_ROOT) -> Path:
    """Returns the actual Bakta database directory (bakta/db-full/).
    This is what gets mounted into Docker and passed to the tool."""
    return db_root / "bakta" / _BAKTA_SUBDIR


def is_checkm_present(db_root: Path = DEFAULT_DB_ROOT) -> bool:
    """Return True only if the CheckM database appears complete.
    Checks that all expected top-level directories exist inside the db path."""
    db = checkm_db_path(db_root)
    return all((db / marker).is_dir() for marker in _CHECKM_MARKERS)


def is_bakta_present(db_root: Path = DEFAULT_DB_ROOT) -> bool:
    """Return True only if the Bakta database appears complete.
    Checks for bakta.db inside the db-full/ subdirectory."""
    return (bakta_db_path(db_root) / _BAKTA_MARKER).exists()


def pgap_data_dir(data_dir: Path = _DEFAULT_PGAP_DATA_DIR) -> Path:
    """Return the PGAP supplemental data directory."""
    return data_dir


def is_pgap_present(data_dir: Path = _DEFAULT_PGAP_DATA_DIR) -> bool:
    """Return True if PGAP supplemental data appears complete.
    pgap.py --update creates a versioned input-VERSION.BUILD/ subdirectory.
    We confirm presence by checking that at least one such directory exists."""
    if not data_dir.exists():
        return False
    import glob
    return bool(glob.glob(str(data_dir / "input-*.build*")))


def phigaro_db_path() -> Path:
    """Return the BactoWise-managed Phigaro database directory."""
    return _PHIGARO_DB_DIR


def is_phigaro_present() -> bool:
    """Return True if the Phigaro database appears complete.
    Checks for config.yml (full setup) or the allpvoghmms HMM file (database
    downloaded but setup may have been interrupted before config was written).
    Either is sufficient to skip re-downloading the ~1.5 GB HMM profiles."""
    config_ok = (_PHIGARO_DB_DIR / _PHIGARO_DB_MARKER).exists()
    hmm_ok    = (_PHIGARO_DB_DIR / "pvog" / _PHIGARO_HMM_FILE).exists()
    return config_ok or hmm_ok


def platon_db_path() -> Path:
    """Return the BactoWise-managed Platon database directory."""
    return _PLATON_DB_DIR


def is_platon_present() -> bool:
    """Return True if the Platon database appears complete.
    The database extracts to a db/ directory; we confirm it is non-empty."""
    return _PLATON_DB_DIR.exists() and any(_PLATON_DB_DIR.iterdir())


def download_platon(force: bool = False, db_root: Path = DEFAULT_DB_ROOT) -> Path:
    """
    Download and extract the Platon database from Zenodo.

    The tarball (~1.6 GB) is downloaded to a temporary file alongside the
    destination directory, then extracted in-place and the tarball deleted.

    Parameters
    ----------
    force   : re-download even if already present
    db_root : parent directory for all BactoWise databases
    """
    dest_parent = db_root / "platon"
    dest        = platon_db_path()

    if is_platon_present() and not force:
        print(f"  ✓  Platon database already present at: {dest}")
        print(f"     (use --force-db-download to re-download)")
        return dest

    if force and dest_parent.exists():
        print(f"  Removing existing Platon database at: {dest_parent}")
        shutil.rmtree(dest_parent)

    dest_parent.mkdir(parents=True, exist_ok=True)
    tarball = dest_parent / _PLATON_DB_TARBALL

    print(f"\n  Downloading Platon database (~1.6 GB) → {dest}")
    print(f"  Source: {_PLATON_DB_URL}")

    try:
        _download_with_progress(_PLATON_DB_URL, tarball)
    except Exception as e:
        tarball.unlink(missing_ok=True)
        raise RuntimeError(
            f"Platon download failed: {e}\n"
            f"Check your network connection and try again."
        ) from e

    print(f"  Extracting archive...")
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(path=dest_parent)
    except Exception as e:
        raise RuntimeError(f"Failed to extract Platon tarball: {e}") from e
    finally:
        tarball.unlink(missing_ok=True)

    if not is_platon_present():
        raise RuntimeError(
            f"Platon database extraction appeared to succeed but the expected "
            f"db/ directory was not found inside {dest_parent}."
        )

    print(f"  ✓  Platon database ready at: {dest}\n")
    return dest


def eggnog_db_path() -> Path:
    """Return the BactoWise-managed EggNOG database directory."""
    return _EGGNOG_DB_DIR


def is_eggnog_present() -> bool:
    """Return True if the EggNOG database appears complete.
    Checks for eggnog_proteins.dmnd — the DIAMOND search database, which is
    the largest file and is downloaded after eggnog.db."""
    return (_EGGNOG_DB_DIR / _EGGNOG_DB_MARKER).exists()


def download_eggnog(force: bool = False) -> Path:
    """
    Download the EggNOG-mapper databases directly from eggnog5.embl.de.

    We download directly rather than via download_eggnog_data.py because
    the bundled script has a stale hostname (eggnogdb.embl.de → 404).
    The correct URLs use eggnog5.embl.de.

    Downloads ~20 GB total:
        eggnog.db            — main annotation database (~15 GB, gzipped)
        eggnog_proteins.dmnd — DIAMOND search database (~4 GB, gzipped)
        eggnog.taxa.tar.gz   — taxonomy database (small)

    Parameters
    ----------
    force : re-download even if already present
    """
    _BASE_URL  = "http://eggnog5.embl.de/download/emapperdb-5.0.2"
    _FILES = [
        ("eggnog.taxa.tar.gz",        "tar"),
        ("eggnog.db.gz",              "gz"),
        ("eggnog_proteins.dmnd.gz",   "gz"),
    ]

    if is_eggnog_present() and not force:
        print(f"  ✓  EggNOG database already present at: {_EGGNOG_DB_DIR}")
        print(f"     (use --force-db-download to re-download)")
        return _EGGNOG_DB_DIR

    if force and _EGGNOG_DB_DIR.exists():
        import shutil as _shutil
        print(f"  Removing existing EggNOG database at: {_EGGNOG_DB_DIR}")
        _shutil.rmtree(_EGGNOG_DB_DIR)

    _EGGNOG_DB_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  Downloading EggNOG databases (~20 GB) → {_EGGNOG_DB_DIR}")
    print(f"  Note: eggnog.db is ~15 GB — this will take a while.\n")

    import gzip as _gzip

    for filename, fmt in _FILES:
        url  = f"{_BASE_URL}/{filename}"
        dest = _EGGNOG_DB_DIR / filename

        print(f"  Downloading {filename}...")
        try:
            _download_resumable(url, dest)
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise RuntimeError(
                f"EggNOG download failed for {filename}: {e}\n"
                f"Check your network connection and try again."
            ) from e

        print(f"  Decompressing {filename}...")
        try:
            if fmt == "gz":
                # Decompress .gz → strip the .gz extension
                out_path = _EGGNOG_DB_DIR / filename[:-3]  # remove .gz
                with _gzip.open(dest, "rb") as f_in:
                    with open(out_path, "wb") as f_out:
                        while True:
                            chunk = f_in.read(1024 * 1024 * 64)  # 64 MB chunks
                            if not chunk:
                                break
                            f_out.write(chunk)
            elif fmt == "tar":
                with tarfile.open(dest, "r:gz") as tf:
                    tf.extractall(path=_EGGNOG_DB_DIR)
        except Exception as e:
            raise RuntimeError(f"Failed to decompress {filename}: {e}") from e
        finally:
            dest.unlink(missing_ok=True)

        print(f"  ✓  {filename} ready.")

    if not is_eggnog_present():
        raise RuntimeError(
            f"EggNOG download appeared to succeed but {_EGGNOG_DB_MARKER} "
            f"was not found at {_EGGNOG_DB_DIR}."
        )

    print(f"  ✓  EggNOG database ready at: {_EGGNOG_DB_DIR}\n")
    return _EGGNOG_DB_DIR
    """
    Return the path to the AMRFinderPlus database directory if found, or None.

    Database structure inside the conda env:
        share/amrfinderplus/data/
            latest/          ← symlink to most recent version
            YYYY-MM-DD.#/    ← versioned directory containing AMRProt, AMR.LIB etc.

    We glob for AMRProt inside any subdirectory of the data/ directory.
    """
    import os
    import glob as _glob
    candidates = list(_CONDA_ROOT_CANDIDATES)

    for env_var in ("CONDA_PREFIX_1", "CONDA_PREFIX"):
        val = os.environ.get(env_var)
        if val:
            p = Path(val)
            for candidate in (p, p.parent.parent):
                if (candidate / "envs").exists():
                    candidates.insert(0, candidate)

    for root in candidates:
        data_dir = root / _AMRFINDERPLUS_DB_SUBPATH
        if not data_dir.exists():
            continue
        # Look for AMRProt in any subdirectory (versioned or latest symlink)
        matches = _glob.glob(str(data_dir / "*" / _AMRFINDERPLUS_DB_MARKER))
        if matches:
            return Path(matches[0]).parent   # return the versioned dir

    return None


def is_amrfinderplus_db_present() -> bool:
    """Return True if the AMRFinderPlus database is present inside the conda env."""
    return amrfinderplus_db_path() is not None


def is_spifinder_present() -> bool:
    """Return True if SPIFinder script and database are both present.
    Checks for the script and at least one .fsa file in the database directory,
    rather than a specific filename, so upstream renames don't break the check.
    """
    import glob as _glob
    if not _SPIFINDER_SCRIPT.exists():
        return False
    if not _SPIFINDER_DB_DIR.exists():
        return False
    return bool(_glob.glob(str(_SPIFINDER_DB_DIR / _SPIFINDER_DB_MARKER_GLOB)))


def spifinder_db_path() -> Path:
    """Return the SPIFinder database directory path."""
    return _SPIFINDER_DB_DIR


def spifinder_script_path() -> Path:
    """Return the path to the spifinder.py script."""
    return _SPIFINDER_SCRIPT


def download_spifinder(force: bool = False) -> Path:
    """
    Install SPIFinder by cloning both the tool and the database from Bitbucket.

    No Docker image or conda package exists for SPIFinder — it is a Python
    script distributed only via Bitbucket. Both repos are cloned into
    ~/.bactowise/databases/spifinder/:
        spifinder/      — the Python script (spifinder.py)
        spifinder_db/   — the BLAST database files (~3 MB)

    Parameters
    ----------
    force : re-clone even if already present (pulls latest commits)
    """
    _TOOL_URL = "https://bitbucket.org/genomicepidemiology/spifinder.git"
    _DB_URL   = "https://bitbucket.org/genomicepidemiology/spifinder_db.git"

    if is_spifinder_present() and not force:
        print(f"  ✓  SPIFinder already present at: {_SPIFINDER_ROOT}")
        print(f"     (use --force-db-download to re-clone)")
        return _SPIFINDER_DB_DIR

    _SPIFINDER_ROOT.mkdir(parents=True, exist_ok=True)

    tool_dir = _SPIFINDER_ROOT / "spifinder"
    db_dir   = _SPIFINDER_DB_DIR

    for label, url, dest in [
        ("SPIFinder script", _TOOL_URL, tool_dir),
        ("SPIFinder database", _DB_URL, db_dir),
    ]:
        if dest.exists() and force:
            print(f"  Removing existing {label} at: {dest}")
            shutil.rmtree(dest)

        if dest.exists():
            print(f"  ✓  {label} already present at: {dest}")
            continue

        print(f"\n  Cloning {label}...")
        print(f"  Source: {url}")
        result = subprocess.run(
            ["git", "clone", url, str(dest)],
            text=True,
        )
        if result.returncode != 0 or not dest.exists():
            raise RuntimeError(
                f"Failed to clone {label} from {url}\n"
                f"Ensure git is installed and Bitbucket is reachable."
            )
        print(f"  ✓  {label} cloned to: {dest}")

    if not is_spifinder_present():
        raise RuntimeError(
            f"SPIFinder installation appeared to succeed but expected files "
            f"were not found at {_SPIFINDER_ROOT}."
        )

    print(f"  ✓  SPIFinder ready at: {_SPIFINDER_ROOT}\n")
    return _SPIFINDER_DB_DIR


# ── Download orchestration ─────────────────────────────────────────────────────

def download_all(
    force: bool = False,
    db_root: Path = DEFAULT_DB_ROOT,
    checkm: bool = True,
    bakta: bool = True,
    pgap: bool = False,
) -> None:
    """Download CheckM, Bakta, and/or PGAP databases.

    Parameters
    ----------
    force   : re-download even if already present
    db_root : parent directory for CheckM/Bakta databases
    checkm  : whether to download the CheckM database
    bakta   : whether to download the Bakta database
    pgap    : whether to download the PGAP supplemental data (~30 GB)
    """
    if checkm:
        download_checkm(force=force, db_root=db_root)
    if bakta:
        download_bakta(force=force, db_root=db_root)
    if pgap:
        download_pgap(force=force)


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
    Download the Bakta full database using bakta_db.

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
    dest     = bakta_db_path(db_root)   # db-full/ inside dest_dir

    if is_bakta_present(db_root) and not force:
        print(f"  ✓  Bakta database already present at: {dest}")
        print(f"     (use --force-db-download to re-download)")
        return dest

    if force and dest_dir.exists():
        print(f"  Removing existing Bakta database at: {dest_dir}")
        shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    cmd = _bakta_db_download_cmd(dest_dir)

    print(f"\n  Downloading Bakta database (full, ~71 GB) → {dest}")
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


def download_pgap(force: bool = False, data_dir: Path = _DEFAULT_PGAP_DATA_DIR) -> Path:
    """
    Download the pgap.py wrapper script and the PGAP supplemental data.

    Step 1: Download pgap.py from NCBI to ~/.bactowise/bin/pgap.py if not
            already present (or if force=True). This replaces the manual
            curl/chmod/mv steps previously required.

    Step 2: Run pgap.py --update to download the supplemental data (~30 GB)
            to ~/.bactowise/databases/pgap/ via PGAP_INPUT_DIR.

    Parameters
    ----------
    force    : re-download pgap.py and re-run --update even if already present
    data_dir : PGAP data directory (default: ~/.bactowise/databases/pgap/)
    """
    # ── Step 1: ensure pgap.py is available ───────────────────────────────────
    pgap_bin = _ensure_pgap_wrapper(force=force)

    # ── Step 2: download supplemental data ────────────────────────────────────
    if is_pgap_present(data_dir) and not force:
        print(f"  ✓  PGAP supplemental data already present at: {data_dir}")
        print(f"     (use --force-db-download to re-download)")
        return data_dir

    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Downloading PGAP supplemental data (~30 GB) → {data_dir}")
    print(f"  This is a one-time step and will take a while.\n")

    # Set PGAP_INPUT_DIR so pgap.py downloads to our managed location.
    # pgap.py respects this env var as of its 2022 release.
    import os
    env = {**os.environ, "PGAP_INPUT_DIR": str(data_dir)}

    result = subprocess.run([pgap_bin, "--update"], env=env, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"pgap.py --update failed (exit {result.returncode}).\n"
            f"Check the output above for details."
        )

    if not is_pgap_present(data_dir):
        raise RuntimeError(
            f"pgap.py --update appeared to succeed but {_PGAP_DATA_MARKER} "
            f"was not found at {data_dir}.\n"
            f"Try running manually: {pgap_bin} --update"
        )

    print(f"\n  ✓  PGAP supplemental data ready at: {data_dir}\n")
    return data_dir


def _ensure_pgap_wrapper(force: bool = False) -> str:
    """
    Ensure pgap.py is available, downloading it to ~/.bactowise/bin/ if needed.

    Checks in order:
    1. Already on PATH (e.g. user installed it manually) — use as-is.
    2. Previously downloaded to ~/.bactowise/bin/pgap.py — use that.
    3. Neither found (or force=True) — download from NCBI GitHub.

    Returns the path to the pgap.py binary.
    """
    # Already on PATH — use it directly
    on_path = shutil.which("pgap.py") or shutil.which("pgap")
    if on_path and not force:
        print(f"  ✓  pgap.py found on PATH: {on_path}")
        return on_path

    managed = _PGAP_BIN_DIR / "pgap.py"

    if managed.exists() and not force:
        print(f"  ✓  pgap.py already downloaded: {managed}")
        return str(managed)

    # Download from NCBI
    _PGAP_BIN_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading pgap.py wrapper → {managed}")
    print(f"  Source: {_PGAP_WRAPPER_URL}\n")

    try:
        urllib.request.urlretrieve(_PGAP_WRAPPER_URL, managed)
    except Exception as e:
        managed.unlink(missing_ok=True)
        raise RuntimeError(
            f"Failed to download pgap.py: {e}\n"
            f"Check your network connection and try again."
        ) from e

    # Make executable
    import stat
    managed.chmod(managed.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  ✓  pgap.py downloaded and made executable: {managed}\n")
    return str(managed)


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
        # Run via /bin/bash -c so the shell inherits the container's PATH,
        # making bakta_db available. Matches the approach in Bakta's own docs.
        return [
            singularity_bin, "exec",
            "--bind", f"{dest_dir}:/db_output:rw",
            str(sif),
            "/bin/bash", "-c",
            "bakta_db download --output /db_output --type full",
        ]

    # ── Option 2: Docker ─────────────────────────────────────────────────────
    if shutil.which("docker"):
        image_ref = _bakta_image_ref()
        _ensure_docker_image(image_ref)
        print(f"  Using Docker image: {image_ref}")
        # Same /bin/bash -c approach as recommended in Bakta's official docs:
        # docker run -v ... --entrypoint /bin/bash image -c "bakta_db download ..."
        return [
            "docker", "run", "--rm",
            "--volume", f"{dest_dir}:/db_output",
            "--entrypoint", "/bin/bash",
            image_ref,
            "-c", "bakta_db download --output /db_output --type full",
        ]

    # ── Option 3: bakta_db on PATH ────────────────────────────────────────────
    if shutil.which("bakta_db"):
        return ["bakta_db", "download", "--output", str(dest_dir), "--type", "full"]

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


def _download_resumable(url: str, dest: Path, max_retries: int = 10) -> None:
    """
    Download a URL to dest with resume support and automatic retries.

    Uses HTTP Range requests to continue from the byte offset already
    written to disk. This means a network dropout at 90% does not restart
    from zero — the next attempt picks up where it left off.

    Retries up to max_retries times with a short backoff between attempts.
    Falls back to a full (non-resumable) download on the first attempt if
    the server does not support Range requests.
    """
    import time

    attempt  = 0
    backoff  = 5  # seconds between retries

    while attempt < max_retries:
        attempt += 1
        existing = dest.stat().st_size if dest.exists() else 0

        try:
            req = urllib.request.Request(url)
            if existing:
                req.add_header("Range", f"bytes={existing}-")

            with urllib.request.urlopen(req, timeout=120) as resp:
                total_size   = int(resp.headers.get("Content-Length", 0))
                is_partial   = resp.status == 206  # HTTP 206 Partial Content
                total_bytes  = (existing + total_size) if is_partial else total_size

                mode = "ab" if is_partial else "wb"
                if is_partial:
                    print(
                        f"\r  Resuming from {existing / 1024**2:.0f} MB "
                        f"(attempt {attempt}/{max_retries})...",
                        flush=True,
                    )
                elif attempt > 1:
                    print(
                        f"\r  Restarting download "
                        f"(attempt {attempt}/{max_retries}, server does not support resume)...",
                        flush=True,
                    )

                written = existing if is_partial else 0
                bar_len = 30

                with open(dest, mode) as f:
                    while True:
                        chunk = resp.read(1024 * 1024)  # 1 MB chunks
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)

                        if total_bytes > 0:
                            pct    = min(written * 100 / total_bytes, 100)
                            filled = int(bar_len * pct / 100)
                            bar    = "█" * filled + "░" * (bar_len - filled)
                            print(
                                f"\r  [{bar}] {pct:5.1f}%  "
                                f"{written / 1024**2:.0f}/{total_bytes / 1024**2:.0f} MB",
                                end="", flush=True,
                            )
                        else:
                            print(
                                f"\r  Downloaded {written / 1024**2:.0f} MB…",
                                end="", flush=True,
                            )

            print()  # newline after progress bar
            return  # success

        except Exception as e:
            print()  # newline after partial progress bar
            if attempt < max_retries:
                print(
                    f"  ⚠  Download interrupted: {e}\n"
                    f"  Retrying in {backoff}s (attempt {attempt}/{max_retries})..."
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)  # exponential backoff, cap at 60s
            else:
                raise RuntimeError(
                    f"Download failed after {max_retries} attempts: {e}"
                ) from e
