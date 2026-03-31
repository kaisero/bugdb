"""BugDB - Palo Alto Networks Bug Database Viewer."""

from pathlib import Path


def _read_version() -> str:
    """Read version from VERSION file."""
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    # Fallback for installed package
    try:
        from importlib.metadata import version
        return version("bugdb")
    except Exception:
        return "0.0.0"


__version__ = _read_version()
