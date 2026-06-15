"""Developer-mode facade for engine/host_loop callers.

Reads the per-process boolean exposed by the C++ host as
_dauntless_host.developer_mode. Uses getattr with a False default so a stale
.so without the attribute degrades to "production mode" rather than raising.
"""
import logging
from typing import Callable

import _dauntless_host

_logger = logging.getLogger(__name__)

# Mapping of GLFW key code -> (handler, description). Populated by
# register_dev_keybinding() in engine/dev_keybindings.py and elsewhere.
# dispatch_dev_key() consults this table only when is_enabled() is True.
_dev_keybindings: dict[int, tuple[Callable, str]] = {}


def is_enabled() -> bool:
    """True iff the binary was launched with --developer."""
    return bool(getattr(_dauntless_host, "developer_mode", False))


def log_swallowed(context: str, exc: BaseException) -> None:
    """Surface an otherwise-silent swallowed exception — dev mode only.

    Many ``except Exception: pass`` sites in the engine are deliberate
    robustness shims (optional SDK methods, teardown that must not throw,
    the static Python build's missing stdlib). They are correct to swallow
    but invisible when something genuinely misbehaves. Replacing the bare
    ``pass`` with ``dev_mode.log_swallowed("<operation>", exc)`` keeps the
    success path byte-identical in production: this is a no-op unless
    ``is_enabled()`` (one ``getattr`` bool check, then early return — no
    I/O, no formatting). Under ``--developer`` it logs the context string
    and exception at WARNING via stdlib ``logging``, which a developer can
    grep for when a silent failure is suspected.

    `context` is a short, specific operation name (e.g. "destroy bridge
    instance", "ship.SetRadius fallback") — it is what a developer will
    search for.
    """
    if not is_enabled():
        return
    _logger.warning("swallowed exception [%s]: %r", context, exc)


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


# Ordered list of dev-mode pause-menu entries. Distinct from
# _dev_keybindings — a keybinding fires on key press and is not
# inherently a menu row; a menu entry has a clickable label and a
# handler. Caller-controlled order; duplicates not de-duped.
_dev_pause_menu_entries: list[tuple[str, Callable]] = []


def register_dev_pause_menu_entry(label: str, handler: Callable) -> None:
    """Register a dev-only pause-menu row.

    Rows added here appear in default_pause_menu when dev_mode is on.
    They appear in registration order, after the normal Exit / Cancel
    rows, with no visible separator between sections.
    """
    _dev_pause_menu_entries.append((label, handler))


def dev_pause_menu_entries() -> list[tuple[str, Callable]]:
    """Return registered (label, handler) pairs in registration order.

    Read by default_pause_menu when dev mode is enabled. Callers must
    not mutate the returned list — it is a live reference to the
    registry.
    """
    return _dev_pause_menu_entries


def dev_only(fn: Callable) -> Callable:
    """Wrap `fn` so it executes only in dev mode (else returns None).

    Intended for temporary behaviour overrides — e.g. forcing invulnerability
    while testing AI, bypassing a damage gate while iterating on a script.
    Wrapping with @dev_only keeps the override callable from leaking into
    production play without per-call `if dev_mode.is_enabled()` boilerplate.
    """
    def wrapper(*args, **kwargs):
        if not is_enabled():
            return None
        return fn(*args, **kwargs)
    return wrapper
