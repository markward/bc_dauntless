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


def register_dev_keybinding(key: int, handler: Callable, description: str) -> None:
    """Register a handler that runs when `key` is pressed in dev mode.

    `key` is a GLFW key code (see _dauntless_host.keys.KEY_*).
    `description` is shown in the pause menu's developer section.
    Re-registering the same key replaces the prior entry.
    """
    _dev_keybindings[key] = (handler, description)


def dispatch_dev_key(key: int) -> bool:
    """Run the handler registered for `key`. Returns True if a handler ran.

    Returns False when dev mode is off, the key is unregistered, or both.
    The host loop calls this from its input switch before falling through
    to normal gameplay handling.
    """
    if not is_enabled():
        return False
    entry = _dev_keybindings.get(key)
    if entry is None:
        return False
    entry[0]()
    return True


def keybinding_descriptions() -> list[tuple[int, str]]:
    """Return registered (key, description) pairs sorted by key code.

    Used by the pause menu to render the developer section.
    """
    return sorted((k, desc) for k, (_, desc) in _dev_keybindings.items())
