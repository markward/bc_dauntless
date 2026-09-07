"""The first-run folder picker's flow. The ONLY module that may prompt.

engine/paths.py stays pure on purpose. tools/ scripts, pytest and CI all
reach paths.current() lazily, and none of them can dismiss a modal
dialog -- a picker reachable from the library would hang them. Keeping
the prompt here, called from exactly one place in host_loop.run(), makes
that true by construction rather than by discipline.

`prompt_for_missing` below is the legacy blocking-loop flow; `host_loop.py`
is still the only caller. `engine.ui.first_run_panel.FirstRunPanel` is its
replacement -- a CEF-rendered screen instead of bare OS dialogs -- and once
`host_loop._resolve_paths_or_report` is rewired onto it, `prompt_for_missing`,
`_message_for`, `_TITLES` and `_VALIDATORS` all become dead and should be
deleted together with that rewiring, in the same change that removes the
call site. `_default_picker` is NOT part of that: `FirstRunPanel` uses it
too, as its own default picker.

Nothing in this module captures a path at import.
"""

from typing import Callable, Dict, Optional

from engine import paths

_TITLES = {
    "game": "Select your Bridge Commander game folder",  # paths-guard: kind label, matches paths.py's own "game"/"sdk" vocabulary
    "sdk": "Select your Bridge Commander SDK folder",  # paths-guard: kind label, not a path segment
}

_VALIDATORS = {"game": paths.validate_game_root, "sdk": paths.validate_sdk_root}  # paths-guard: kind labels keying paths.py's own validators


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


def _message_for(verdict, subject: str = "That folder") -> str:
    """What the panel says. Empty when there is nothing to report.

    `subject` names whose folder failed: "That folder" fits a retry, where
    the player just picked the thing being described. The very first ask
    can also carry a failure -- a stale settings.json or a typo'd CLI flag
    -- that the player never chose, so its caller passes "The configured
    folder" instead; "That folder" there would have no referent.
    """
    if verdict is None:
        return ""
    parts = []
    if verdict.missing:
        parts.append(subject + " is missing: " + ", ".join(verdict.missing))
    if verdict.hint:
        parts.append(verdict.hint)
    return "  ".join(parts)


# SUPERSEDED by engine.ui.first_run_panel.FirstRunPanel, which drives the
# same choice through a CEF screen instead of bare OS dialogs. This function
# stays only because engine/host_loop.py's _resolve_paths_or_report still
# calls it -- delete it (and _message_for, _TITLES, _VALIDATORS above)
# together with that call site, in the same change, not before: host_loop
# is its only caller, and removing this without rewiring that caller leaves
# the tree red (AttributeError at boot on any unresolved-paths run).
def prompt_for_missing(
    resolution,
    picker: Optional[Callable[[str, str], Optional[str]]] = None,
    argv=None,
    env=None,
    store=None,
):
    """Ask for each unresolved root; return a Resolution built from the answers.

    Asks for game first, then sdk, skipping any root that already
    resolved. An invalid choice re-prompts saying what was wrong; a cancel
    stops immediately. A root that validated before a later cancel is
    KEPT, so the next launch only asks for what is still missing.

    A blank answer is treated as a cancellation. Path("") stringifies to
    "." at construction, so once built it cannot be told apart from a
    deliberate Path(".") -- the rejection has to happen here, before any
    Path exists.
    """
    if picker is None:
        picker = _default_picker

    picked: Dict[str, str] = {}
    for kind in ("game", "sdk"):  # paths-guard: kind labels, matches Resolution.source()/.validation()'s own vocabulary
        already = resolution.game if kind == "game" else resolution.sdk  # paths-guard: kind label, not a path segment
        if already is not None:
            continue
        message = _message_for(
            resolution.validation(kind), subject="The configured folder")
        cancelled = False
        while True:
            choice = picker(_TITLES[kind], message)
            if choice is None or not str(choice).strip():
                cancelled = True
                break
            verdict = _VALIDATORS[kind](choice)
            if verdict.ok:
                picked[kind] = str(verdict.root)
                break
            message = _message_for(verdict)
        if cancelled:
            break

    if not picked:
        return resolution
    return paths.resolve(argv=argv, env=env, store=store, picked=picked)
