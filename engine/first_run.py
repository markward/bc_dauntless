"""The first-run folder picker's native dialog. The ONLY module that may
open it.

engine/paths.py stays pure on purpose. tools/ scripts, pytest and CI all
reach paths.current() lazily, and none of them can dismiss a modal
dialog -- a picker reachable from the library would hang them. Keeping
the picker here, reached from exactly one place (engine.ui.first_run_panel.
FirstRunPanel's default), makes that true by construction rather than by
discipline.

Nothing in this module captures a path at import.
"""

from typing import Optional


def _default_picker(title: str, message: str) -> Optional[str]:
    """The native panel, when this build and platform have one.

    Deliberately getattr-guarded rather than declared in the renderer's
    _REQUIRED_BINDINGS: this runs BEFORE validate_bindings(), so a stale
    .so reaches here first and would raise instead of being reported. A
    missing binding is simply "no picker", which is the same branch as a
    cancel and as a platform with no implementation.

    The call itself is also guarded: a binding that raises -- signature
    drift, a non-UTF-8 path, anything -- collapses to the same "no picker"
    answer rather than an unhandled traceback escaping run(). That keeps
    "anything went wrong with the picker" a single branch, the property
    folder_picker.h already documents.
    """
    try:
        import _dauntless_host
    except ImportError:
        return None
    pick = getattr(_dauntless_host, "pick_folder", None)
    if pick is None:
        return None
    try:
        return pick(title, message)
    except Exception:
        return None
