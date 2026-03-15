"""
bactowise/utils/config_manager.py

Manages the lifecycle of the active pipeline configuration at
~/.bactowise/config/pipeline.yaml.

Design
------
BactoWise ships a canonical pipeline.yaml bundled inside the package at
bactowise/config/pipeline.yaml. On first run (or after `bactowise init`),
this file is copied to ~/.bactowise/config/pipeline.yaml — the "installed"
config — and that installed copy is what the pipeline reads at runtime.

The installed config is never overwritten automatically. If BactoWise is
upgraded and the bundled config changes, the user must explicitly run
`bactowise init --reset` to apply the update. This ensures that any comments
or modifications a developer has made to the installed config (e.g. uncommenting
the PGAP block) survive an upgrade.

Public API
----------
    active_config_path()     → Path to the installed config (may not exist yet)
    bundled_config_path()    → Path to the config bundled inside the package
    ensure_config()          → Install from bundle if not already installed
    install_config(reset)    → (Re)install from bundle, optionally overwriting
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Where the installed config lives
_CONFIG_DIR  = Path("~/.bactowise/config").expanduser()
_CONFIG_FILE = _CONFIG_DIR / "pipeline.yaml"

# Where the bundled (package-shipped) config lives.
# importlib.resources is the correct way to locate package data files — it
# works whether the package is installed as a wheel, a conda package, or run
# directly from source.
def bundled_config_path() -> Path:
    """Return the path to the pipeline.yaml bundled inside the package."""
    try:
        # Python 3.9+
        from importlib.resources import files
        ref = files("bactowise.config").joinpath("pipeline.yaml")
        # Materialise to a real Path (works for both zip and directory installs)
        with ref as p:
            return Path(str(p))
    except Exception:
        # Fallback: resolve relative to this file's location
        return Path(__file__).parent.parent / "config" / "pipeline.yaml"


def active_config_path() -> Path:
    """Return the path where the active (installed) config lives."""
    return _CONFIG_FILE


def ensure_config() -> Path:
    """
    Install the bundled config to ~/.bactowise/config/pipeline.yaml if it
    does not already exist. Does nothing if the file is already present.

    Returns the path to the active config.
    """
    if _CONFIG_FILE.exists():
        return _CONFIG_FILE
    return install_config(reset=False)


def install_config(reset: bool = False) -> Path:
    """
    Copy the bundled pipeline.yaml to ~/.bactowise/config/pipeline.yaml.

    Parameters
    ----------
    reset : if True, overwrite any existing installed config.
            if False, raise FileExistsError if the config is already present.
    """
    if _CONFIG_FILE.exists() and not reset:
        raise FileExistsError(
            f"Config already installed at: {_CONFIG_FILE}\n"
            f"Use --reset to overwrite it with the bundled version."
        )

    src = bundled_config_path()
    if not src.exists():
        raise RuntimeError(
            f"Bundled config not found at: {src}\n"
            f"The BactoWise installation may be incomplete. Try reinstalling."
        )

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, _CONFIG_FILE)
    return _CONFIG_FILE
