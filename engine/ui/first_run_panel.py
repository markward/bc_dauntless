"""The "Select Bridge Commander Install" screen's state machine.

Every decision the screen makes is here. The CEF page renders the payload
this class emits and reports button presses back; it holds no logic of its
own, because CEF is software-rasterized in this project and there is no
headless render to test a page against.

Nothing in this module captures a path at import.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, Optional

from engine import first_run, paths
from engine.ui.panel import Panel

TITLE = "Select Bridge Commander Install"

_UNSET = "Not set"
_FOUND = "Bridge Commander install found"
_NOT_AN_INSTALL = "Not a Bridge Commander install"

_ROWS = (
    # kind, label, picker title
    ("game", "Game folder",  # paths-guard: kind label, matches Resolution.source()'s vocabulary
     "Select your Bridge Commander game folder"),
    ("sdk", "SDK folder",    # paths-guard: kind label, matches Resolution.source()'s vocabulary
     "Select your Bridge Commander SDK folder"),
)

_VALIDATORS = {
    "game": paths.validate_game_root,  # paths-guard: kind label, keys paths.py's own validators
    "sdk": paths.validate_sdk_root,    # paths-guard: kind label, keys paths.py's own validators
}


class FirstRunPanel(Panel):
    """One row per BC root, Browse each, Continue gated on both validating.

    `picker` is the folder chooser -- injected so tests never open a modal.
    `resolver` maps a {kind: path} dict to a Resolution; injected for the
    same reason paths.resolve() takes argv/env/store, so a test can supply a
    store without touching the developer's real settings.json.
    """

    def __init__(self, resolution, picker: Optional[Callable[[str, str], Optional[str]]] = None,
                 resolver: Optional[Callable[[Dict[str, str]], object]] = None):
        super().__init__()
        self._picker = picker if picker is not None else first_run._default_picker
        self._resolver = resolver if resolver is not None else _default_resolver
        self._resolution = resolution
        # Rows the player answered this session, kind -> validated path str.
        self._picked: Dict[str, str] = {}
        # Rows the player answered WRONGLY, kind -> hint (or ""). Cleared by a
        # later valid answer. Separate from _picked so a bad answer can be
        # reported without becoming a candidate root.
        self._rejected: Dict[str, str] = {}
        self._outcome: Optional[str] = None
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str:
        return "first-run"

    @property
    def outcome(self) -> Optional[str]:
        """None while the screen is running; "continue" or "quit" when done."""
        return self._outcome

    @property
    def resolution(self):
        """The best Resolution so far -- including a root validated before a
        quit, which persist() stores so the next launch asks only for what is
        still missing."""
        return self._resolution

    # ── state ───────────────────────────────────────────────────────────
    def _root_for(self, kind: str):
        return self._resolution.game if kind == "game" else self._resolution.sdk  # paths-guard: kind label, not a path segment

    def _status_for(self, kind: str) -> dict:
        if kind in self._rejected:
            return {"status": _NOT_AN_INSTALL, "hint": self._rejected[kind], "ok": False}
        root = self._root_for(kind)
        if root is None:
            return {"status": _UNSET, "hint": "", "ok": False}
        return {"status": _FOUND, "hint": "", "ok": True}

    def _snapshot(self) -> dict:
        rows = []
        for kind, label, _title in _ROWS:
            root = self._root_for(kind)
            row = {"kind": kind, "label": label, "path": str(root) if root else ""}
            row.update(self._status_for(kind))
            rows.append(row)
        return {
            "title": TITLE,
            "rows": rows,
            "can_continue": self._resolution.ok,
        }

    # ── Panel contract ──────────────────────────────────────────────────
    def render_payload(self) -> Optional[str]:
        script = "setFirstRun(" + json.dumps(self._snapshot()) + ");"
        if script == self._last_pushed:
            return None
        self._last_pushed = script
        return script

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("browse:"):
            return self._browse(action[len("browse:"):])
        if action == "continue":
            # Inert unless both roots validate -- the page disables the
            # button, but the page is not the authority on this.
            if self._resolution.ok:
                self._outcome = "continue"
            return True
        if action == "quit":
            self._outcome = "quit"
            return True
        return False

    def invalidate(self) -> None:
        """Drop the payload snapshot so the next render re-emits. Called on
        CEF document load, which is the only moment the page is guaranteed
        able to receive it -- a push before the page's scripts have run is
        silently dropped."""
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        """ESC does what Quit does, so the two can never disagree."""
        self.dispatch_event("quit")

    # ── browse ──────────────────────────────────────────────────────────
    def _browse(self, kind: str) -> bool:
        if kind not in _VALIDATORS:
            return False
        title = next(t for k, _label, t in _ROWS if k == kind)
        choice = self._picker(title, "")
        # No answer: a cancel, a platform with no picker, or a stale .so.
        # All three mean the same thing -- leave the row exactly as it was.
        # Blank is rejected HERE, before a Path exists: Path("") stringifies
        # to "." at construction and is then indistinguishable from a
        # deliberate Path(".").
        if choice is None or not str(choice).strip():
            return True
        verdict = _VALIDATORS[kind](choice)
        if not verdict.ok:
            self._rejected[kind] = verdict.hint or ""
            return True
        self._rejected.pop(kind, None)
        self._picked[kind] = str(verdict.root)
        self._resolution = self._resolver(dict(self._picked))
        return True


def _default_resolver(picked: Dict[str, str]):
    return paths.resolve(picked=picked)
