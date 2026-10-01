"""The pre-boot Mods screen's state machine (spec 2026-10-01 mod ships §1).

Every decision is here; the CEF page (js/mods_screen.js) renders the payload
and reports clicks and committed text. Two modes:
  gate -- incomplete mod ships are editable rows; Continue writes them.
  home -- every mod ship read-only; Play boots (the future mod manager's home).
"""
from __future__ import annotations

import json
from collections import namedtuple
from typing import Callable, Optional
from urllib.parse import unquote

from engine.ship_catalog import catalog
from engine.ship_catalog.gate_writer import GateWriteError
from engine.ship_catalog.schema import parse_dauntless
from engine.ship_catalog.tables import ERA_IDS, ERAS, MANDATORY, ROLES
from engine.ui import ship_icons
from engine.ui.panel import Panel

WriteRow = namedtuple("WriteRow", "mod ship_id attr answers")

_HEADERS = {"gate": "New mod ships need details", "home": "Mod Ships"}
_INTROS = {
    "gate": ("These ships come from mods that don't say which era, role or species "
             "they belong to. Fill in the missing details once. Your answers are "
             "saved into each mod's own folder, so you won't be asked again."),
    "home": "Every ship your installed mods add, and the details Dauntless uses for it.",
}


class _Row:
    def __init__(self, record, editable: bool, answers: dict):
        self.record = record
        self.editable = editable
        self.answers = answers          # title/species/era/role/playable/variant_of/class_default
        self.ticked = False

    @property
    def file(self) -> str:
        return self.record.ship_id

    def class_key(self) -> str:
        return (self.answers.get("variant_of") or "").strip().lower()


class ModsScreenPanel(Panel):
    def __init__(self, mode: str, editable: list, readonly: list, *, species, stock_classes,
                 writer: Optional[Callable] = None, suggest: Optional[Callable] = None,
                 error: str = "") -> None:
        super().__init__()
        self._mode = mode
        self._species = list(species)
        self._stock = dict(stock_classes)   # title -> values dict (era/role/species/playable)
        self._stock_keys = {t.strip().lower(): v for t, v in self._stock.items()}
        self._writer = writer
        suggest = suggest or catalog.suggestions
        self._rows = []
        for r in editable:
            answers = dict(suggest(r))
            answers.update(r.values)
            if r.variant_of:
                answers["variant_of"] = r.variant_of
            answers["class_default"] = r.class_default
            self._rows.append(_Row(r, True, answers))
        for r in readonly:
            answers = dict(r.values, variant_of=r.variant_of, class_default=r.class_default)
            self._rows.append(_Row(r, False, answers))
        self._outcome: Optional[str] = None
        self._error = error
        self._last_pushed: Optional[str] = None
        self.visible = True

    # ── Panel contract ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "mods"

    @property
    def outcome(self) -> Optional[str]:
        return self._outcome

    teardown_script = "setModsScreen(null);"

    def invalidate(self) -> None:
        super().invalidate()
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._mode == "home":
            self._outcome = "play"

    def render_payload(self) -> Optional[str]:
        script = "setModsScreen(" + json.dumps(self._snapshot()) + ");"
        if script == self._last_pushed:
            return None
        self._last_pushed = script
        return script

    def dispatch_event(self, action: str) -> bool:
        if action in ("continue", "skip", "play", "quit"):
            getattr(self, "_on_" + action)()
            return True
        if action == "clear-ticks":
            for r in self._rows:
                r.ticked = False
            return True
        if action.startswith("tick:"):
            r = self._find(action[5:])
            if r is not None and r.editable:
                r.ticked = not r.ticked
            return True
        if action.startswith("tick-mod:"):
            mod = action[9:]
            mine = [r for r in self._rows if r.editable and r.record.mod == mod]
            on = not all(r.ticked for r in mine)
            for r in mine:
                r.ticked = on
            return True
        if action.startswith("star:"):
            r = self._find(action[5:])
            if r is not None and r.editable:
                key = r.class_key()
                if key and key not in self._stock_keys and self._locked_default(key) is None:
                    for m in self._members(key):
                        if m.editable:
                            m.answers["class_default"] = False
                    r.answers["class_default"] = True
            return True
        if action.startswith("set:"):
            parts = action.split(":", 3)
            if len(parts) != 4:
                return False
            _, file, field, raw = parts
            r = self._find(file)
            if r is None or not r.editable:
                return True
            value = unquote(raw)
            for t in (self._ticked() if r.ticked else [r]):
                self._apply(t, field, value)
            return True
        return False

    # ── edits ───────────────────────────────────────────────────────────
    def _apply(self, r: _Row, field: str, value: str) -> None:
        a = r.answers
        if field in ("title", "species"):
            a[field] = value.strip() or None
        elif field == "variant_of":
            a["variant_of"] = value.strip() or None
            a["class_default"] = False
        elif field == "role":
            a["role"] = value if value in {x.id for x in ROLES} else None
        elif field == "playable":
            a["playable"] = value == "1"
        elif field == "era" and value == "all":
            a["era"] = ("all",)
        elif field in ("era-from", "era-to") and value in ERA_IDS:
            i = ERA_IDS.index(value)
            lo, hi = (ERA_IDS.index(a["era"][0]), ERA_IDS.index(a["era"][1])) \
                if isinstance(a.get("era"), tuple) and a["era"] != ("all",) else (i, i)
            if field == "era-from":
                lo, hi = i, max(hi, i)
            else:
                lo, hi = min(lo, i), i
            a["era"] = (ERA_IDS[lo], ERA_IDS[hi])

    # ── validation ──────────────────────────────────────────────────────
    def _row_missing(self, r: _Row) -> tuple:
        raw = {k: v for k, v in r.answers.items() if k in MANDATORY and v is not None}
        if "era" in raw:
            raw["era"] = list(raw["era"]) if raw["era"] != ("all",) else "all"
        return parse_dauntless(raw).missing

    def _members(self, key: str) -> list:
        return [m for m in self._rows if m.class_key() == key]

    def _locked_default(self, key: str):
        """The read-only member of `key`'s class already marked
        class_default, if any -- it is the class's FIXED default and no
        editable member (nor the star control) may override it."""
        if not key:
            return None
        for m in self._members(key):
            if not m.editable and m.answers.get("class_default"):
                return m
        return None

    def _conflict(self, r: _Row) -> str:
        key = r.class_key()
        if not key:
            return ""
        members = [(m.answers.get("title") or m.file,
                    {k: m.answers[k] for k in ("era", "role", "species", "playable")
                     if m.answers.get(k) is not None}, ()) for m in self._members(key)]
        stock_values = self._stock_keys.get(key)
        if stock_values is not None:
            title = next(t for t in self._stock if t.strip().lower() == key)
            members.append((title, {k: stock_values[k] for k in
                                     ("era", "role", "species", "playable")
                                     if k in stock_values}, ()))
        if len(members) < 2:
            return ""
        _v, _m, errors = catalog.combine_class(members)
        return "; ".join(errors)

    def _default_flags(self) -> dict:
        flags = {}
        seen = set()
        for r in self._rows:
            key = r.class_key()
            if not key or key in self._stock_keys or key in seen:
                continue
            seen.add(key)
            group = self._members(key)
            locked = self._locked_default(key)
            if locked is not None:
                for m in group:
                    flags[m.file] = m is locked
                continue
            idx = catalog.resolve_class_default(
                [(m.answers.get("title") or m.file, bool(m.answers.get("class_default")))
                 for m in group], key)
            for i, m in enumerate(group):
                flags[m.file] = i == idx
        return flags

    def _ready(self) -> bool:
        return all(not self._row_missing(r) and not self._conflict(r)
                   for r in self._rows if r.editable)

    # ── outcomes ────────────────────────────────────────────────────────
    def _on_continue(self) -> None:
        if self._mode != "gate" or not self._ready():
            return
        flags = self._default_flags()
        rows = []
        for r in self._rows:
            if not r.editable:
                continue
            answers = {k: r.answers.get(k) for k in MANDATORY}
            # The zz file UPDATEs the author's dict, so undoing an author
            # value takes an explicit write: class_default always 1 or 0,
            # and a cleared variant_of written as None.
            if r.answers.get("variant_of"):
                answers["variant_of"] = r.answers["variant_of"]
                answers["class_default"] = flags.get(r.file, False)
            elif r.record.variant_of:
                answers["variant_of"] = None
            rows.append(WriteRow(r.record.mod, r.file, r.record.shipdef_attr, answers))
        if self._writer is not None:
            try:
                self._writer(rows)
            except GateWriteError as exc:
                self._error = str(exc)
                return
        self._outcome = "continue"

    def _on_skip(self) -> None:
        if self._mode == "gate":
            self._outcome = "skip"

    def _on_play(self) -> None:
        if self._mode == "home":
            self._outcome = "play"

    def _on_quit(self) -> None:
        self._outcome = "quit"

    # ── payload ─────────────────────────────────────────────────────────
    def _find(self, file: str):
        return next((r for r in self._rows if r.file == file), None)

    def _ticked(self) -> list:
        return [r for r in self._rows if r.editable and r.ticked]

    def _snapshot(self) -> dict:
        flags = self._default_flags()
        rows, by_mod = [], {}
        for r in self._rows:
            a = r.answers
            era = a.get("era")
            era_s = None if era is None else ("all" if era == ("all",) else "%s-%s" % era)
            key = r.class_key()
            rows.append({
                "file": r.file, "mod": r.record.mod, "icon": r.record.icon,
                "icon_url": ship_icons.icon_path_for_species(r.record.icon) or "",
                "title": a.get("title"), "variant_of": a.get("variant_of"),
                "is_default": flags.get(r.file, False),
                "stock_class": bool(key) and key in self._stock_keys,
                "star_locked": bool(key) and key not in self._stock_keys
                               and self._locked_default(key) is not None,
                "era": era_s, "role": a.get("role"), "species": a.get("species"),
                "playable": a.get("playable"), "editable": r.editable, "ticked": r.ticked,
                "missing": list(self._row_missing(r)) if r.editable else [],
                "conflict": self._conflict(r) if r.editable else "",
            })
            m = by_mod.setdefault(r.record.mod, {"name": r.record.mod, "ships": 0, "keys": set()})
            m["ships"] += 1
            m["keys"].add(key or "#" + r.file.lower())
        incomplete = [x for x in rows if x["editable"] and (x["missing"] or x["conflict"])]
        status = ("All ships complete" if not incomplete else
                  "%d %s details" % (len(incomplete), "ship needs" if len(incomplete) == 1 else "ships need"))
        return {
            "mode": self._mode, "header": _HEADERS[self._mode], "intro": _INTROS[self._mode],
            "rows": rows,
            "mods": [{"name": m["name"], "ships": m["ships"], "classes": len(m["keys"])}
                     for m in by_mod.values()],
            "species": self._species, "stock_classes": sorted(self._stock),
            "eras": [{"id": e.id, "tag": e.tag, "name": e.name} for e in ERAS],
            "roles": [{"id": r.id, "label": r.label} for r in ROLES],
            "ticked": len(self._ticked()), "status": status,
            "status_ok": not incomplete, "can_continue": self._ready(),
            "error": self._error,
        }
