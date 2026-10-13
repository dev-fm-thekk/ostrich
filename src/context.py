"""
context.py
==========
Loads the Windows naming-convention context (context.json) and exposes
helpers that normalise any app name or file path before it is passed to
the OS / tool functions.

Usage
-----
    from context import resolve_app_name, validate_path

    canonical = resolve_app_name("Google Chrome")  # → "chrome"
    canonical = resolve_app_name("Notepad.exe")    # → "notepad"
    canonical = resolve_app_name("unknown_app")    # → "unknown_app"  (passthrough)
"""

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Load context.json once at import time
# ---------------------------------------------------------------------------

_CONTEXT_PATH = Path(__file__).parent / "context.json"

with _CONTEXT_PATH.open(encoding="utf-8") as _f:
    _CTX: dict = json.load(_f)

_ALIASES: dict[str, str] = _CTX.get("app_aliases", {})
_PATH_RULES: dict = _CTX.get("path_conventions", {})


# ---------------------------------------------------------------------------
# App-name resolution
# ---------------------------------------------------------------------------

def resolve_app_name(raw: str) -> str:
    """Normalise a human/model-supplied app name to the Windows executable name.

    Lookup is case-insensitive and strips surrounding whitespace and common
    suffixes like `.exe`.

    Parameters
    ----------
    raw : str
        The app name as supplied by the model or user
        (e.g. ``"Google Chrome"``, ``"CHROME.EXE"``, ``"notepad "``).

    Returns
    -------
    str
        The canonical Windows executable name (e.g. ``"chrome"``),
        or *raw* unchanged if no alias is found.

    Examples
    --------
    >>> resolve_app_name("Google Chrome")
    'chrome'
    >>> resolve_app_name("NOTEPAD.EXE")
    'notepad'
    >>> resolve_app_name("myprivateapp")
    'myprivateapp'
    """
    normalised = raw.strip().lower()
    # Also try without .exe suffix so "chrome.exe" → look up "chrome"
    without_exe = re.sub(r"\.exe$", "", normalised)

    return _ALIASES.get(normalised) or _ALIASES.get(without_exe) or raw


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def validate_path(path_str: str) -> tuple[bool, str]:
    """Check a Windows file path against the naming conventions in context.json.

    Parameters
    ----------
    path_str : str
        The file or directory path to validate.

    Returns
    -------
    tuple[bool, str]
        ``(is_valid, message)`` — if invalid, *message* explains why.

    Examples
    --------
    >>> validate_path("C:\\Users\\NIYATHA\\file.txt")
    (True, 'Path is valid.')
    >>> validate_path("C:\\bad:name\\file.txt")
    (False, "Path contains forbidden character: ':'")
    """
    forbidden: list[str] = _PATH_RULES.get("forbidden_chars", [])
    reserved: list[str] = _PATH_RULES.get("reserved_names", [])
    max_len: int = _PATH_RULES.get("max_path_length", 260)

    if len(path_str) > max_len:
        return False, f"Path exceeds Windows MAX_PATH ({max_len} chars)."

    # Check forbidden characters (skip drive-colon at position 1)
    check_str = path_str[2:] if len(path_str) > 2 and path_str[1] == ":" else path_str
    for ch in forbidden:
        if ch in check_str:
            return False, f"Path contains forbidden character: '{ch}'"

    # Check reserved names in any path component
    parts = Path(path_str).parts
    for part in parts:
        stem = Path(part).stem.upper()
        if stem in reserved:
            return False, f"Path component '{part}' is a reserved Windows name."

    return True, "Path is valid."
