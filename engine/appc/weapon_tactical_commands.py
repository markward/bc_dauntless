"""Surface 2 of the weapons-config feature: equipment-gated command rows on the
F2 Tactical officer menu.

The SDK builds the Tactical menu once per bridge load
(``Bridge/TacticalMenuHandlers.CreateTacticalMenu``); the ``CrewMenuPanel`` then
re-snapshots the menu's buttons every tick and routes clicks back as SDK events.
We append five weapon/defense command rows to that menu, gated by the player's
equipment, with dynamic labels — all reusing the surface-agnostic mutators in
:mod:`engine.appc.weapon_config` so the panel (Surface 1) and this menu stay in
sync.

``sync(player)`` is idempotent and cheap: safe to call every tick. It self-heals
the per-bridge-load rebuild — when the SDK throws the old Tactical menu away and
builds a fresh one, ``sync`` detects the tracked button is no longer among the
menu's children and re-adds it.

Click path (confirmed against the SDK + dauntless shims):

    CEF click -> crew_menu_panel.dispatch_event("click:<wid>")
              -> STButton.SendActivationEvent()            (characters.py)
              -> App.g_kEventManager.AddEvent(button._event)
              -> menu.ProcessEvent(event)                  (STMenu is a
                 TGEventHandlerObject via ObjectClass)
              -> _resolve_handler("engine.appc.weapon_tactical_commands._on_command")
              -> _on_command(menu, event): event.GetInt() -> command.action(player)

Each button carries ONE custom event type (``ET_WEAPON_TACTICAL_CMD``) with a
DISTINCT subevent int per command; a single dispatcher handler switches on
``pEvent.GetInt()``.  The dispatcher resolves the player from the current game so
it never acts on a ship captured at build time.

Everything is raise-safe: a missing subsystem / no player / no menu must never
throw into the tick loop.
"""
from __future__ import annotations

from engine.appc import weapon_config


# ── Tactical menu label ───────────────────────────────────────────────────────
# The SDK labels the menu with pDatabase.GetString("Tactical") from
# "data/TGL/Bridge Menus.tgl"; the dauntless localization stub returns the key
# itself when the TGL is absent, so "Tactical" is the headless label.  Resolve
# through the same DB at runtime so an installed game's localized label matches.

def _tactical_label() -> str:
    try:
        import App
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        s = db.GetString("Tactical")
        try:
            App.g_kLocalizationManager.Unload(db)
        except Exception:
            pass
        label = str(s)
        return label or "Tactical"
    except Exception:
        return "Tactical"


# Convenience constant for callers/tests that want the headless label directly.
TACTICAL_MENU_LABEL = "Tactical"


# ── Event wiring ──────────────────────────────────────────────────────────────
# ONE custom event type; a DISTINCT subevent int per command (kept stable so a
# button built on an earlier tick still routes correctly).

def _event_type() -> int:
    """Allocate (once) and return the shared command event type."""
    global _ET_WEAPON_TACTICAL_CMD
    if _ET_WEAPON_TACTICAL_CMD is None:
        try:
            import App
            _ET_WEAPON_TACTICAL_CMD = App.Game_GetNextEventType()
        except Exception:
            # Fixed fallback in the private engine range (never collides with
            # SDK Appc ids); only hit if App is unavailable.
            _ET_WEAPON_TACTICAL_CMD = 0x1400
    return _ET_WEAPON_TACTICAL_CMD


_ET_WEAPON_TACTICAL_CMD: "int | None" = None

_HANDLER_PATH = "engine.appc.weapon_tactical_commands._on_command"


# ── Label helpers ─────────────────────────────────────────────────────────────

def _next_torpedo_type_name(ship) -> str:
    """Name of the ammo type ``cycle_torpedo_type`` would advance to (wraps).

    Empty string when there is no torpedo system or ≤1 loaded type.
    """
    torps = weapon_config._torpedo_system(ship)
    if torps is None:
        return ""
    try:
        # Only SELECTABLE slots (available > 0 or unlimited) — mirrors
        # CycleAmmoType, so an empty type like PhasedPlasma is never offered.
        slots = torps.GetSelectableAmmoSlots()
    except Exception:
        return ""
    if len(slots) <= 1:
        return ""
    try:
        idx = slots.index(torps.GetCurrentAmmoSlot())
    except Exception:
        idx = 0
    nxt = torps.GetAmmoType(slots[(idx + 1) % len(slots)])
    if nxt is None or not hasattr(nxt, "GetAmmoName"):
        return ""
    try:
        return nxt.GetAmmoName() or ""
    except Exception:
        return ""


# ── Command table (data-driven) ───────────────────────────────────────────────
# Each command: key, subevent int, gate(cfg)->bool, label(ship, cfg)->str,
# action(ship)->None.  Reuses weapon_config for every mutation + gate flag.

class _Command:
    __slots__ = ("key", "subevent", "gate", "label", "action")

    def __init__(self, key, subevent, gate, label, action):
        self.key = key
        self.subevent = subevent
        self.gate = gate
        self.label = label
        self.action = action


def _phaser_label(ship, cfg) -> str:
    # Label reflects the RESULT of clicking.
    to = "Full" if cfg.get("phaser_intensity") == "Light" else "Light"
    return "Set Phasers to " + to


def _type_label(ship, cfg) -> str:
    return "Use " + _next_torpedo_type_name(ship) + " Torpedoes"


def _spread_label(ship, cfg) -> str:
    # BC's "spread" toggle IS the firing-chain selector (SetFiringChainMode,
    # audited §2.10) — the label is the hardpoint-authored chain name
    # (Single/Dual/Quad on Galaxy/Sovereign), not a computed word.
    return "Torpedo Spread " + cfg.get("spread", "")


def _tractor_label(ship, cfg) -> str:
    return ("Disengage" if cfg.get("tractor_on") else "Engage") + " Tractor"


def _cloak_label(ship, cfg) -> str:
    return ("Disengage" if cfg.get("cloak_on") else "Engage") + " Cloak"


_COMMANDS = [
    _Command(
        "phasers", 1,
        lambda cfg: bool(cfg.get("has_phasers")),
        _phaser_label,
        weapon_config.toggle_phaser_intensity,
    ),
    _Command(
        "torp_type", 2,
        lambda cfg: bool(cfg.get("torp_types_cyclable")),
        _type_label,
        weapon_config.cycle_torpedo_type,
    ),
    _Command(
        "torp_spread", 3,
        lambda cfg: len(cfg.get("spread_options", [])) > 1,
        _spread_label,
        weapon_config.cycle_torpedo_spread,
    ),
    _Command(
        "tractor", 4,
        lambda cfg: bool(cfg.get("tractor_present")),
        _tractor_label,
        weapon_config.toggle_tractor,
    ),
    _Command(
        "cloak", 5,
        lambda cfg: bool(cfg.get("cloak_present")),
        _cloak_label,
        weapon_config.toggle_cloak,
    ),
]

_BY_SUBEVENT = {c.subevent: c for c in _COMMANDS}


# ── Per-menu tracking of the buttons we own ───────────────────────────────────
# Keyed by menu identity so a rebuilt menu (fresh object) starts clean and the
# old menu's entry is naturally abandoned.  Value: {command_key: STButton}.

_tracked: "dict[int, dict]" = {}


def _tracked_for(menu) -> dict:
    return _tracked.setdefault(id(menu), {})


# ── sync ──────────────────────────────────────────────────────────────────────

def _current_player():
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _find_tactical_menu():
    try:
        from engine.appc.windows import TacticalControlWindow
        tcw = TacticalControlWindow.GetInstance()
        return tcw.FindMenu(_tactical_label())
    except Exception:
        return None


def sync(player) -> None:
    """Reconcile the weapon/defense command rows on the Tactical menu.

    Idempotent, raise-safe, cheap when there's no Tactical menu.  Adds gated
    commands (once, wired to the dispatcher), removes ungated ones, and updates
    every present command's label to reflect current state.
    """
    try:
        menu = _find_tactical_menu()
        if menu is None:
            return
        cfg = weapon_config.read_weapon_config(player)
        tracked = _tracked_for(menu)
        children = menu.__dict__.get("_children", [])
        for cmd in _COMMANDS:
            gated = cmd.gate(cfg)
            btn = tracked.get(cmd.key)
            # Detect a rebuilt menu: a button we think we own is no longer a
            # child of this menu object.
            present = btn is not None and btn in children
            if gated:
                if not present:
                    btn = _make_button(cmd, menu)
                    tracked[cmd.key] = btn
                    menu.AddChild(btn)
                try:
                    btn.SetLabel(cmd.label(player, cfg))
                except Exception:
                    pass
            else:
                if present:
                    _remove_button(menu, btn)
                tracked.pop(cmd.key, None)
    except Exception:
        # Never propagate into the tick loop.
        return


def _make_button(cmd, menu):
    import App
    event = App.TGIntEvent_Create()
    event.SetEventType(_event_type())
    event.SetInt(cmd.subevent)
    event.SetDestination(menu)
    btn = App.STButton_CreateW("", event)
    # Register the single dispatcher for the shared event type (idempotent:
    # AddPythonFuncHandlerForInstance appends, so guard against re-registering
    # on a menu we've already wired).
    _ensure_handler(menu)
    return btn


def _ensure_handler(menu) -> None:
    et = _event_type()
    handlers = menu.__dict__.get("_handlers", {})
    if _HANDLER_PATH in handlers.get(et, []):
        return
    menu.AddPythonFuncHandlerForInstance(et, _HANDLER_PATH)


def _remove_button(menu, btn) -> None:
    try:
        menu.DeleteChild(btn)
    except Exception:
        pass


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _on_command(pObject, pEvent) -> None:
    """Single dispatcher: subevent int -> command.action(current player).

    Raise-safe — a missing subsystem / no player is a silent no-op.
    """
    try:
        subevent = pEvent.GetInt()
    except Exception:
        return
    cmd = _BY_SUBEVENT.get(subevent)
    if cmd is None:
        return
    player = _current_player()
    if player is None:
        return
    try:
        cmd.action(player)
    except Exception:
        pass
