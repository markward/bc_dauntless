"""The build's identity: a semver string, and what a shipped copy reports.

VERSION is the one place the number lives. pyproject.toml must agree, which
tests/unit/test_version_consistency.py enforces -- two hand-maintained copies
of a version drift silently, and the one that drifts is always the one nobody
reads.

WHY A RUNTIME IDENTITY AT ALL. A published zip that cannot say what it is
makes a bug report unanswerable: with main moving as fast as it does, "last
week's build" names nothing. So scripts/package.py records the commit it was
staged from in the packaged marker, and `banner()` puts it in the log at boot.

The COMMIT matters more than the number. 0.1.0 does not locate code; a hash
does. The number is for people, the hash is for us.

A CHECKOUT has no marker and no recorded commit -- it is whatever the working
tree happens to be, which may be dirty -- so it reports itself as a checkout
rather than inventing a provenance it cannot stand behind.
"""
from __future__ import annotations

import json
from typing import Any, Dict

#: Semantic version of the engine. Bump on release; keep pyproject.toml in step.
VERSION = "0.1.0"

#: Marker keys scripts/package.py writes. Read defensively: a marker written by
#: an older packaging script, or hand-edited, must not stop the game booting.
_KEY_VERSION = "version"
_KEY_COMMIT = "commit"
_KEY_BUILT = "built"
_KEY_PLATFORM = "platform"


def read_build_info() -> Dict[str, Any]:
    """The packaged marker's contents, or {} for a checkout.

    Resolved at USE, never at import (CLAUDE.md): engine.paths.configure() is
    callable again after boot, so a module-level read would be stale the moment
    the first-run picker changes a root.

    Never raises. A corrupt or unreadable marker degrades to {} -- the build
    identity is diagnostics, and losing it must not cost the player a launch.
    """
    from engine import paths
    try:
        marker = paths.PROJECT_ROOT / paths.PACKAGED_MARKER
        if not marker.is_file():
            return {}
        data = json.loads(marker.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def banner() -> str:
    """One line naming this build, for the top of the log.

    Packaged:  BC Dauntless 0.1.0 (b5196e7a2, 2026-10-22T11:18:00Z, windows-x64)
    Checkout:  BC Dauntless 0.1.0 (checkout)
    """
    info = read_build_info()
    if not info:
        return f"BC Dauntless {VERSION} (checkout)"
    bits = [str(info.get(_KEY_COMMIT) or "unknown commit")]
    for key in (_KEY_BUILT, _KEY_PLATFORM):
        value = info.get(key)
        if value:
            bits.append(str(value))
    # The marker's version wins over VERSION: in a packaged build the marker is
    # what the packaging script actually stamped, and if the two disagree the
    # shipped file is the truth about the shipped bytes.
    version = info.get(_KEY_VERSION) or VERSION
    return f"BC Dauntless {version} (" + ", ".join(bits) + ")"
