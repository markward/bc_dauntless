"""Developer-mode facade for engine/host_loop callers.

Reads the per-process boolean exposed by the C++ host as
_dauntless_host.developer_mode. Uses getattr with a False default so a stale
.so without the attribute degrades to "production mode" rather than raising.
"""
from typing import Callable

import _dauntless_host

# Mapping of GLFW key code -> (handler, description). Populated by
# register_dev_keybinding() in engine/dev_keybindings.py and elsewhere.
# dispatch_dev_key() consults this table only when is_enabled() is True.
_dev_keybindings: dict[int, tuple[Callable, str]] = {}


def is_enabled() -> bool:
    """True iff the binary was launched with --developer."""
    return bool(getattr(_dauntless_host, "developer_mode", False))
