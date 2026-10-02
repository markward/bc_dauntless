"""Quick Battle setup screen: the Python-owned state machine (spec §3).

Python owns every piece of state -- the scenario (engine.quickbattle.scenario),
the add target, the selected card, the Details draft, the pending
confirmation, the era/species filters and the preset bookkeeping. The CEF page
(js/quick_battle_setup.js) renders the two pushes and reports verbs:

  setQuickBattleCatalog(payload)  on open, on invalidate and whenever the
                                  catalog generation changes
  setQuickBattleSetup(payload)    the §3.2 state; skipped when unchanged

The setup is per-run (D8): the scenario lives here, in memory, and never on
disk -- only presets are written. The panel registers itself as the spawn
provider, so XO Start/Restart (which bypass the screen) spawn the current
setup. Every scenario change re-syncs the SDK's preload manifests, player type
and XO Start button outside a battle (spec §4.1).

Spec: docs/superpowers/specs/2026-10-02-quickbattle-setup-screen-design.md
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional
from urllib.parse import unquote

from engine.quickbattle import scenario as sc
from engine.ui.panel import Panel

_log = logging.getLogger(__name__)

_UNSET = object()

_ALLEGIANCE_LABEL = {"friendly": "Friendly", "enemy": "Enemy", "neutral": "Neutral"}
_DIRECTION_LABEL = {"fore": "Fore", "aft": "Aft", "port": "Port",
                    "starboard": "Starboard", "dorsal": "Dorsal", "ventral": "Ventral"}
_DISTANCE_LABEL = {"close": "Close", "standard": "Standard", "long": "Long",
                   "out_of_range": "Out of range"}
_DIFFICULTY_LABEL = {"low": "Low", "medium": "Medium", "high": "High"}
_DRAFT_FIELDS = {"allegiance": sc.ALLEGIANCES, "direction": sc.DIRECTIONS,
                 "distance": sc.DISTANCE_IDS, "difficulty": tuple(sc.DIFFICULTY_LEVEL)}


def _default_catalog() -> list:
    """The ships the screen lists: complete catalog entries the player did not
    skip at the gate this session. Read at call time (the catalog is cached
    underneath, so this is cheap enough to poll)."""
    from engine import ship_catalog
    skipped = ship_catalog.skipped()          # lower-cased ids
    return [e for e in ship_catalog.entries()
            if e.complete and e.ship_id.lower() not in skipped]


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


class QuickBattleSetupPanel(Panel):
    _UNSET = _UNSET

    def __init__(self, on_start: Optional[Callable[[], None]] = None, *,
                 catalog_fn: Optional[Callable[[], list]] = None, presets=None,
                 stats=None, bio_fn: Optional[Callable] = None,
                 qb_module=_UNSET) -> None:
        super().__init__()
        self._on_start = on_start
        self._visible = False
        self._last_pushed: Optional[str] = None
        self._catalog_fn = catalog_fn or _default_catalog
        self._presets_obj = presets           # resolved lazily (_presets)
        if stats is None:
            from engine.quickbattle.stats import StatsCache
            stats = StatsCache()
        self._stats = stats
        if bio_fn is None:
            from engine.quickbattle.bios import ship_bio
            bio_fn = ship_bio
        self._bio_fn = bio_fn
        # The QuickBattle script module. _UNSET -> lazy import; None -> no SDK.
        self._qb_module = qb_module

        self._scenario = sc.default_scenario()
        self._target = self._scenario.first_non_player_group().id
        self._selected: Optional[str] = None
        self._draft: Optional[dict] = None
        self._confirm: Optional[dict] = None
        self._eras = set(self._default_eras())
        self._species = {"Federation"}
        self._preset: Optional[str] = None
        self._pending_js = ""

        # Catalog: read lazily on first use (open, render or plan).
        self._generation = None
        self._entries: list = []
        self._index: dict = {}
        self._catalog_push_due = False

        from engine.quickbattle import spawn
        spawn.set_provider(self.current_plan)

    @staticmethod
    def _default_eras():
        from engine.ship_catalog import DEFAULT_ERAS
        return DEFAULT_ERAS

    # ── Panel contract ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "quick-battle-setup"

    @property
    def scenario(self) -> sc.Scenario:
        return self._scenario

    @property
    def _presets(self):
        if self._presets_obj is None:
            from engine.quickbattle.presets import load_presets
            self._presets_obj = load_presets()
        return self._presets_obj

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._catalog_push_due = True
        self.visible = True

    def close(self) -> None:
        self._pending_js = ""
        self.visible = False

    def invalidate(self) -> None:
        # A reloaded page has lost BOTH pushes.
        super().invalidate()
        self._last_pushed = None
        self._catalog_push_due = True

    def handle_key_esc(self) -> None:
        # The page closes an open popover first; otherwise it sends `esc`
        # back (spec §3.6). ESC and the on-screen controls never disagree.
        if self._visible:
            self._pending_js = "qbEscape();"
            self.mark_due()

    # ── SDK ─────────────────────────────────────────────────────────────
    def _qb(self):
        """Resolve the QuickBattle module (cached). _UNSET -> import attempt
        (None on failure); an injected stub/None is returned as-is."""
        m = self._qb_module
        if m is self._UNSET:
            try:
                import importlib
                m = importlib.import_module("QuickBattle.QuickBattle")
            except Exception:
                m = None
            self._qb_module = m
        return m

    def _fire_close_dialog(self) -> None:
        """Post ET_CLOSE_DIALOG to g_pXO so the SDK closes the config dialog:
        clears g_bDialogUp (which _sync_quick_battle_panel mirrors to hide this
        panel) and re-enables the XO config button so it can reopen. Best-effort."""
        m = self._qb()
        if m is None:
            return
        et = getattr(m, "ET_CLOSE_DIALOG", None)
        xo = getattr(m, "g_pXO", None)
        if et is None or xo is None:
            return
        try:
            import App
            evt = App.TGEvent_Create()
            evt.SetEventType(et)
            evt.SetDestination(xo)
            App.g_kEventManager.AddEvent(evt)
        except Exception:
            pass

    def _after_change(self) -> None:
        self._last_pushed = None
        qb = self._qb()
        if qb is not None and not getattr(qb, "bInSimulation", 0):
            from engine.quickbattle import spawn
            try:
                spawn.sync_sdk(qb, self.current_plan())
            except Exception as e:            # an unplannable setup must not
                _log.warning("quickbattle SDK sync failed: %s", e)  # kill dispatch

    # ── Catalog ─────────────────────────────────────────────────────────
    def _refresh_catalog(self) -> None:
        entries = list(self._catalog_fn())
        gen = tuple(entries)
        if gen == self._generation:
            return
        from engine.quickbattle import bios
        self._generation = gen
        self._entries = entries
        self._index = sc.catalog_index(entries)
        sc.reconcile(self._scenario, self._index)
        if self._selected is not None and self._ce(self._selected) is None:
            self._selected = None
        self._stats.reset()
        bios.reset()
        self._catalog_push_due = True
        self._last_pushed = None

    def _ce(self, ship_id):
        return self._index.get((ship_id or "").lower())

    def current_plan(self):
        self._refresh_catalog()
        if not self._index:
            return None
        return sc.battle_plan(self._scenario, self._index)

    def _species_table(self) -> list:
        """STOCK_SPECIES in pill order, then any species the listed entries use
        that the table does not know, alphabetically -- catalog.species()'s
        rule, applied to THIS panel's entries."""
        from engine.ship_catalog import STOCK_SPECIES
        known = {s.name.lower() for s in STOCK_SPECIES}
        extra = sorted({e.species for e in self._entries
                        if e.species and e.species.lower() not in known}, key=str.lower)
        return [(s.name, s.flagship) for s in STOCK_SPECIES] + [(n, None) for n in extra]

    @staticmethod
    def _icon(stem):
        if not stem:
            return None
        try:
            from engine.ui import ship_icons
            return ship_icons.icon_path_for_species(stem) or None
        except Exception as e:                # decoration: costs only itself
            _log.info("quickbattle icon %r unavailable: %s", stem, e)
            return None

    @staticmethod
    def _insignia(name):
        try:
            from engine.ship_catalog import insignia_path
            p = insignia_path(name)
            return p.resolve().as_uri() if p is not None else None
        except Exception as e:
            _log.info("quickbattle insignia %r unavailable: %s", name, e)
            return None

    def _catalog_payload(self) -> dict:
        from engine.ship_catalog import ALL_ERAS, ERAS, ROLES
        ships = []
        for ce in self._entries:
            st = self._stats.get(ce.ship_id)
            ships.append({
                "id": ce.ship_id, "title": ce.title or ce.ship_id,
                "species": ce.species, "role": ce.role,
                "era": "all" if ce.era == (ALL_ERAS,) else list(ce.era or ()),
                "playable": bool(ce.playable),
                "variants": [{"name": v.name, "playable": sc.can_be_player(ce, v.name)}
                             for v in ce.variants],
                "icon": self._icon(ce.icon), "bio": self._bio_fn(ce),
                "hull": st.hull if st is not None else None,
                "shields": st.shields if st is not None else None,
            })
        hull_max, shield_max = self._stats.maxima(self._entries)
        return {
            "ships": ships, "hull_max": hull_max, "shield_max": shield_max,
            "eras": [{"id": e.id, "name": e.name, "tag": e.tag, "start": e.start,
                      "end": e.end} for e in ERAS],
            "roles": [{"id": r.id, "label": r.label} for r in ROLES],
            "species": [{"name": n, "insignia": self._insignia(n),
                         "flagship_icon": self._icon(f)}
                        for n, f in self._species_table()],
            "allegiances": [{"id": a, "label": _ALLEGIANCE_LABEL[a]}
                            for a in sc.ALLEGIANCES],
            "directions": [{"id": d, "label": _DIRECTION_LABEL[d]} for d in sc.DIRECTIONS],
            "distances": [{"id": d, "label": _DISTANCE_LABEL[d], "km": sc.DISTANCE_KM[d]}
                          for d in sc.DISTANCE_IDS],
            "difficulties": [{"id": d, "label": _DIFFICULTY_LABEL[d]}
                             for d in sc.DIFFICULTY_LEVEL],
        }

    # ── Setup payload ───────────────────────────────────────────────────
    def _visible_ship(self, ce) -> bool:
        return ce.in_eras(self._eras) and ce.species in self._species

    def _dirty(self) -> bool:
        if self._preset is None:
            return self._scenario.can_start()
        saved = self._presets.load(self._preset)
        return saved is None or not sc.same_setup(self._scenario, saved)

    @staticmethod
    def _group_summary(g) -> str:
        if g.player:
            return "Friendly · escorts form up beside you"
        text = "%s · %s · %s (%g km)" % (
            _ALLEGIANCE_LABEL[g.allegiance], _DIRECTION_LABEL[g.direction],
            _DISTANCE_LABEL[g.distance], sc.DISTANCE_KM[g.distance])
        if g.difficulty != "medium":
            text += " · " + _DIFFICULTY_LABEL[g.difficulty]
        return text

    def _entry_payload(self, e) -> dict:
        ce = self._ce(e.ship)
        variants = ce.variants if ce is not None else ()
        if e.variant:
            label = e.variant
        elif variants:
            label = variants[0].name + " · class default"
        else:
            label = None
        return {"id": e.id, "ship": e.ship,
                "title": (ce.title or ce.ship_id) if ce is not None else e.ship,
                "variant": e.variant, "variant_label": label, "player": e.player,
                "out_of_era": ce is None or not ce.in_eras(self._eras),
                "has_menu": bool(variants) or not e.player}

    def _setup_payload(self) -> dict:
        from engine.ship_catalog import ERA_IDS
        s = self._scenario
        counts = {n: 0 for n, _f in self._species_table()}
        for ce in self._entries:
            if ce.in_eras(self._eras) and ce.species:
                counts[ce.species] = counts.get(ce.species, 0) + 1
        n_ships = sum(len(g.entries) for g in s.groups)
        return {
            "open": True,
            "groups": [{"id": g.id, "name": g.name, "player": g.player,
                        "allegiance": g.allegiance, "direction": g.direction,
                        "distance": g.distance, "difficulty": g.difficulty,
                        "summary": self._group_summary(g),
                        "entries": [self._entry_payload(e) for e in g.entries]}
                       for g in s.groups],
            "target": self._target, "selected": self._selected,
            "draft": dict(self._draft) if self._draft else None,
            "confirm": ({k: self._confirm[k] for k in ("title", "body", "ok")}
                        if self._confirm else None),
            "eras": [e for e in ERA_IDS if e in self._eras],
            "species": sorted(self._species, key=lambda n: (n.lower(), n)),
            "presets": self._presets.names(), "preset": self._preset,
            "dirty": self._dirty(), "can_start": s.can_start(),
            "counts": counts,
            "summary": "%s · %s" % (_plural(len(s.groups), "group"),
                                    _plural(n_ships, "ship")),
        }

    def render_payload(self) -> Optional[str]:
        prefix = self._pending_js
        self._pending_js = ""
        if not self._visible:
            payload = {"open": False}
        else:
            self._refresh_catalog()
            if self._catalog_push_due:
                self._catalog_push_due = False
                prefix += ("setQuickBattleCatalog("
                           + json.dumps(self._catalog_payload()) + ");")
            payload = self._setup_payload()
        out = "setQuickBattleSetup(" + json.dumps(payload) + ");"
        if out == self._last_pushed:
            out = ""
        else:
            self._last_pushed = out
        return (prefix + out) or None

    # ── Dispatch ────────────────────────────────────────────────────────
    def dispatch_event(self, action: str) -> bool:
        verb, _, arg = action.partition(":")
        handler = self._HANDLERS.get(verb)
        if handler is None:
            _log.warning("quick-battle-setup: unknown verb %r", action)
            return False
        self._refresh_catalog()
        ok = bool(handler(self, arg))
        if not ok:
            _log.warning("quick-battle-setup: refused %r", action)
        return ok

    def _retarget(self) -> None:
        if self._scenario.group(self._target) is None:
            g = self._scenario.first_non_player_group() or self._scenario.player_group()
            self._target = g.id

    def _ask(self, title, body, ok, action) -> bool:
        self._confirm = {"title": title, "body": body, "ok": ok, "action": action}
        return True

    # filters and sheet
    def _on_era(self, arg) -> bool:
        from engine.ship_catalog import ERA_IDS
        if arg not in ERA_IDS:
            return False
        self._eras.symmetric_difference_update({arg})
        self._clear_hidden_selection()
        return True

    def _on_species(self, arg) -> bool:
        name = unquote(arg)
        if name not in {n for n, _f in self._species_table()}:
            return False
        self._species.symmetric_difference_update({name})
        self._clear_hidden_selection()
        return True

    def _clear_hidden_selection(self) -> None:
        ce = self._ce(self._selected)
        if ce is None or not self._visible_ship(ce):
            self._selected = None

    def _on_select(self, arg) -> bool:
        ce = self._ce(unquote(arg))
        if ce is None:
            return False
        self._selected = None if self._selected == ce.ship_id else ce.ship_id
        return True

    # adding ships
    def _on_add(self, arg) -> bool:
        ce = self._ce(unquote(arg))
        if ce is None or self._scenario.add_ship(self._target, ce.ship_id) is None:
            return False
        self._after_change()
        return True

    def _on_set_player(self, arg) -> bool:
        ce = self._ce(unquote(arg))
        if ce is None or not sc.can_be_player(ce, None):
            return False
        self._scenario.set_player_ship(ce.ship_id)
        self._after_change()
        return True

    # groups
    def _on_target(self, arg) -> bool:
        if self._scenario.group(arg) is None:
            return False
        self._target = arg
        return True

    def _on_group_new(self, _arg) -> bool:
        self._target = self._scenario.add_group().id
        self._after_change()
        return True

    def _on_details(self, arg) -> bool:
        g = self._scenario.group(arg)
        if g is None:
            return False
        self._draft = {"group": g.id, "allegiance": g.allegiance,
                       "direction": g.direction, "distance": g.distance,
                       "difficulty": g.difficulty}
        return True

    def _on_draft(self, arg) -> bool:
        field, _, value = arg.partition(":")
        if self._draft is None or value not in _DRAFT_FIELDS.get(field, ()):
            return False
        g = self._scenario.group(self._draft["group"])
        if g is None or (g.player and field != "difficulty"):
            return False
        self._draft[field] = value
        return True

    def _on_draft_update(self, _arg) -> bool:
        d = self._draft
        if d is None:
            return False
        ok = self._scenario.update_details(d["group"], d["allegiance"], d["direction"],
                                           d["distance"], d["difficulty"])
        self._draft = None
        if ok:
            self._after_change()
        return ok

    def _on_draft_cancel(self, _arg) -> bool:
        self._draft = None
        return True

    def _on_rename(self, arg) -> bool:
        gid, _, raw = arg.partition(":")
        if self._scenario.group(gid) is None:
            return False
        # An empty or unchanged name is ignored (spec §3.5), not refused.
        if self._scenario.rename_group(gid, unquote(raw)):
            self._after_change()
        return True

    def _on_group_delete(self, arg) -> bool:
        g = self._scenario.group(arg)
        if g is None or g.player:
            return False

        def delete():
            if self._scenario.delete_group(g.id):
                if self._draft is not None and self._draft["group"] == g.id:
                    self._draft = None
                self._retarget()
                self._after_change()

        if not g.entries:
            delete()
            return True
        return self._ask("Delete group?", "Delete %s and its %s?" % (
            g.name, _plural(len(g.entries), "ship")), "Delete", delete)

    # ship rows
    def _on_variant(self, arg) -> bool:
        eid, _, raw = arg.partition(":")
        _g, e = self._scenario.find_entry(eid)
        ce = self._ce(e.ship) if e is not None else None
        if ce is None:
            return False
        name = unquote(raw) or None
        if name is not None and sc.resolve_variant(ce, name) is None:
            return False
        if e.player and not sc.can_be_player(ce, name):
            return False
        self._scenario.set_variant(eid, name)
        self._after_change()
        return True

    def _on_move(self, arg) -> bool:
        eid, _, gid = arg.partition(":")
        if not self._scenario.move_entry(eid, gid):
            return False
        self._after_change()
        return True

    def _on_remove(self, arg) -> bool:
        if not self._scenario.remove_entry(arg):
            return False
        self._after_change()
        return True

    # presets
    def _on_preset_save(self, arg) -> bool:
        name = unquote(arg).strip()
        if not name:
            return False

        def save():
            if self._presets.save(name, self._scenario):
                self._preset = name
                self._last_pushed = None

        if self._presets.exists(name):
            return self._ask(
                "Overwrite preset?",
                "A preset named %s already exists. Replace it with the current scenario?"
                % name, "Overwrite", save)
        save()
        return True

    def _on_preset_load(self, arg) -> bool:
        name = unquote(arg).strip()
        if not self._presets.exists(name):
            return False

        def load():
            loaded = self._presets.load(name)
            if loaded is None:
                return
            sc.reconcile(loaded, self._index)
            self._scenario = loaded
            self._preset = name
            self._target = (loaded.first_non_player_group() or loaded.player_group()).id
            self._draft = None
            self._selected = None
            self._after_change()

        if self._dirty():
            return self._ask("Load preset?", "Your current setup has unsaved changes. "
                             "Load %s anyway?" % name, "Load", load)
        load()
        return True

    def _on_preset_delete(self, arg) -> bool:
        name = unquote(arg).strip()
        if not self._presets.exists(name):
            return False

        def delete():
            if self._presets.delete(name) and self._preset == name:
                self._preset = None
            self._last_pushed = None

        return self._ask("Delete preset?", "Delete preset %s?" % name, "Delete", delete)

    # dialogs
    def _on_confirm(self, _arg) -> bool:
        pending, self._confirm = self._confirm, None
        if pending is None:
            return False
        pending["action"]()
        return True

    def _on_cancel(self, _arg) -> bool:
        self._confirm = None
        return True

    # footer
    def _on_start(self, _arg) -> bool:
        if self._scenario.can_start():
            self._fire_close_dialog()
            if self._on_start is not None:
                self._on_start()
            self.close()
        return True

    def _on_close(self, _arg) -> bool:
        # Faithful close: ET_CLOSE_DIALOG clears g_bDialogUp + re-enables the
        # XO config button; a bare close() would be reopened next tick.
        self._fire_close_dialog()
        self.close()
        return True

    def _on_esc(self, _arg) -> bool:
        if self._confirm is not None:
            self._confirm = None
        elif self._draft is not None:
            self._draft = None
        elif self._selected is not None:
            self._selected = None
        else:
            return self._on_close(_arg)
        return True

    _HANDLERS = {
        "era": _on_era, "species": _on_species, "select": _on_select,
        "add": _on_add, "set-player": _on_set_player,
        "target": _on_target, "group-new": _on_group_new, "details": _on_details,
        "draft": _on_draft, "draft-update": _on_draft_update,
        "draft-cancel": _on_draft_cancel, "rename": _on_rename,
        "group-delete": _on_group_delete,
        "variant": _on_variant, "move": _on_move, "remove": _on_remove,
        "preset-save": _on_preset_save, "preset-load": _on_preset_load,
        "preset-delete": _on_preset_delete,
        "confirm": _on_confirm, "cancel": _on_cancel,
        "start": _on_start, "close": _on_close, "esc": _on_esc,
    }
