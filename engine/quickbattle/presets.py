"""Quick Battle presets: quickbattle_presets.json beside settings.json.

Only presets live on disk -- the current setup is per-run (spec D8). The
bridge_selection pattern: a SettingsStore underneath (atomic writes, corrupt
file quarantined), a small wrapper above. Spec §6.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from engine.quickbattle import scenario as sc

_log = logging.getLogger(__name__)
_SECTION = "presets"


def default_presets_path() -> Path:
    from engine import settings_store
    return settings_store.default_settings_path().parent / "quickbattle_presets.json"


class PresetStore:
    def __init__(self, store):
        self.store = store

    def _all(self) -> dict:
        # No public SettingsStore API returns a whole section's mapping (only
        # per-key get/set and has_section); bridge_selection.py's PinStore
        # uses the same private _section() under the same has_section guard.
        d = self.store._section(_SECTION) if self.store.has_section(_SECTION) else {}
        return dict(d)

    def names(self) -> list:
        return sorted(self._all(), key=lambda n: (n.lower(), n))

    def exists(self, name) -> bool:
        return (name or "").strip() in self._all()

    def load(self, name):
        rec = self._all().get((name or "").strip())
        if not isinstance(rec, dict):
            return None
        try:
            return sc.from_json(rec.get("scenario"))
        except ValueError as e:
            _log.warning("quickbattle preset %r unreadable: %s", name, e)
            return None

    def save(self, name, scenario) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        allp = self._all()
        allp[name] = {"saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                      "scenario": scenario.to_json()}
        self.store.set_section(_SECTION, allp)
        return True

    def delete(self, name) -> bool:
        allp = self._all()
        name = (name or "").strip()
        if name not in allp:
            return False
        del allp[name]
        self.store.set_section(_SECTION, allp)
        return True


def load_presets(path=None) -> PresetStore:
    from engine.settings_store import SettingsStore
    store = SettingsStore(path if path is not None else default_presets_path())
    store.load()
    return PresetStore(store)
