"""Dauntless settings persistence — JSON, loaded at boot, written on change.

Deliberately NOT BC's Options.cfg. TGConfigMapping.SaveConfigFile dumps the
entire in-memory map, and SDK code saves that global at times we don't control
(QuickBattle.py:1202, host_loop.py:5055) — sharing it means our settings get
written by code we don't own.

SettingsStore is section/key addressed and knows nothing about which settings
exist; the SETTINGS table (added alongside it) supplies that.

The "paths" section is RESERVED for the bootstrap tier — where the player's BC
install lives, which has to be readable before anything boots. Nothing writes
or reads it yet; game/ and sdk/ are still hardcoded to PROJECT_ROOT in
host_loop. It is reserved here so the schema never has to change when that
lands, and unknown-section preservation means an older build cannot destroy it.

Spec: docs/superpowers/specs/2026-09-05-settings-persistence-design.md
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from engine import dev_mode

SCHEMA_VERSION = 1

# engine/settings_store.py -> engine/ -> <project root>, matching
# host_loop.PROJECT_ROOT. Kept local rather than imported so the store has no
# dependency on the host loop.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_settings_path() -> Path:
    """Where settings.json lives. A function, not a constant, because this is
    the single seam that has to move if the file ever needs a per-user OS
    config directory — an installed game's own directory may be read-only."""
    return PROJECT_ROOT / "settings.json"


class SettingsStore:
    """INI-shaped JSON: {"version": N, "<section>": {"<key>": value}}.

    The loaded document is retained whole, so unknown sections and unknown
    keys survive a save — an older build cannot silently eat a newer build's
    settings.
    """

    def __init__(self, path=None):
        self._path = Path(path) if path is not None else default_settings_path()
        self._doc: dict = {"version": SCHEMA_VERSION}

    # ── Load ────────────────────────────────────────────────────────────────
    def load(self) -> None:
        """Read the file. Missing is normal; corrupt is quarantined.

        A corrupt file is renamed to <name>.corrupt rather than deleted, so it
        survives for inspection AND the next save isn't blocked by it.
        """
        self._doc = {"version": SCHEMA_VERSION}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore.load read", exc)
            return
        try:
            doc = json.loads(raw)
            if not isinstance(doc, dict):
                raise ValueError("settings root is %s, not an object"
                                 % type(doc).__name__)
        except (ValueError, TypeError) as exc:
            dev_mode.log_swallowed("SettingsStore.load parse", exc)
            self._quarantine()
            return
        self._doc = doc

    def _quarantine(self) -> None:
        try:
            os.replace(self._path,
                       self._path.parent / (self._path.name + ".corrupt"))
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore quarantine", exc)

    # ── Access ──────────────────────────────────────────────────────────────
    def _section(self, section: str) -> dict:
        got = self._doc.get(section)
        return got if isinstance(got, dict) else {}

    def has(self, section: str, key: str) -> bool:
        return key in self._section(section)

    def get(self, section: str, key: str, default=None):
        return self._section(section).get(key, default)

    # ── Mutation (write-through) ────────────────────────────────────────────
    def set(self, section: str, key: str, value) -> None:
        got = self._doc.get(section)
        if not isinstance(got, dict):
            got = {}
            self._doc[section] = got
        got[key] = value
        self._save()

    def reset_section(self, section: str) -> None:
        self._doc.pop(section, None)
        self._save()

    # ── Write ───────────────────────────────────────────────────────────────
    def _save(self) -> None:
        """Temp file + os.replace, so a crash mid-write can't truncate it.

        setdefault (not assignment) on version: a file stamped NEWER than us
        keeps its stamp, so a downgrade doesn't relabel a newer document.
        A failed write is logged and swallowed — the in-memory settings stay
        live and the game keeps running.
        """
        self._doc.setdefault("version", SCHEMA_VERSION)
        tmp = self._path.parent / (self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._doc, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore.save", exc)
            try:
                tmp.unlink()
            except OSError:
                pass
