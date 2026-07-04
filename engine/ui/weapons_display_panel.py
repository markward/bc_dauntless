"""CEF view for the SDK WeaponsDisplay widget.

Player-only panel that sits as the last child of the bottom-right
tactical cluster. Mirrors
``sdk/Build/scripts/Tactical/Interface/WeaponsDisplay.py``: a small
centred ship silhouette with phaser-arc icons rendered above (dorsal
mounts) and below (ventral mounts), torpedo glyphs in the same pane,
and translucent phaser-field indicator overlays that light up while
each bank fires.

The panel header doubles as BC's speed readout — the original game
showed ``Speed {impulse} : {velocity} kph`` where ``impulse`` is the
0-9 throttle notch and ``velocity`` is the ship's current speed in
km/h. See ``sdk/.../BridgeHandlers.py:1389-1396`` (HelmUpdateToolTip)
for the source format. Replaces the separate SpeedDisplay panel —
this is BC's only "current speed" readout on the tactical HUD.

The slicer-generated atlas sprites + the per-mount descriptor
positions come from the existing typed setters on
``SubsystemProperty`` (mirrored onto ``ShipSubsystem.SetProperty``).

Tractor beams are intentionally excluded: stock ``WeaponsDisplay.py``
iterates ``GetPhaserSystem`` + ``GetPulseWeaponSystem`` for energy
weapons and ``GetTorpedoSystem`` for torpedoes — never
``GetTractorBeamSystem``. We match that.

Coordinates: raw pixel positions inside the SDK's WEAPONS_PANE
(~130x110 px at the original game's 640x480 mode). The SDK's
``WeaponsDisplay.py:280-282`` divides by graphics-mode width to
normalise, then the pane's interior pixel size applies the value
back as a literal pixel offset; net effect is "icon top-left at
(x_px, y_px) inside a fixed-size pane". We carry the raw pixel
values through and let the CSS place the silhouette stack at a
matching fixed size so icons land around the centred silhouette
exactly as BC drew them.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.appc import weapon_config
from engine.ui import ship_icons, weapon_icons
from engine.ui.panel import Panel
from engine.ui.species_icons import stem_for_species
from engine.units import GUPS_TO_KPH


# JS event action → shared weapon_config mutator name.  Resolved on the
# weapon_config module at call time (not bound here) so tests can spy on the
# helper via patch().  toggle-view is handled separately — it flips panel-local
# UI state, not a subsystem.
_CONFIG_ACTIONS = {
    "cycle-type": "cycle_torpedo_type",
    "cycle-spread": "cycle_torpedo_spread",
    "cycle-intensity": "toggle_phaser_intensity",
    "toggle-tractor": "toggle_tractor",
    "toggle-cloak": "toggle_cloak",
}


# Stock WeaponsDisplay.py:80,278 iterates only phaser + pulse weapons
# for the upper/lower arc panes and torpedo tubes for the torpedo
# pane. Tractor beams declare icon setters in their hardpoints for
# SDK-completeness but no SDK pane consumes them.
_ICON_SOURCE_SYSTEMS = (
    "GetPhaserSystem",
    "GetPulseWeaponSystem",
    "GetTorpedoSystem",
)


class WeaponsDisplayPanel(Panel):
    @property
    def name(self) -> str:
        return "weapons"

    def __init__(self, player_control=None):
        super().__init__()
        # _PlayerControl owns the integrated _current_speed (GU/s) the
        # SDK helm readout consumes. Optional so unit tests without a
        # live host loop can construct the panel and exercise the
        # snapshot path; in that mode the header shows 0 : 0 kph.
        self._player_control = player_control
        self._last_snapshot: Optional[tuple] = None
        # Whether the weapon-settings view (vs the status silhouette) is shown.
        self._settings_open: bool = False

    # ── Snapshot ────────────────────────────────────────────────────────
    def _snapshot(self) -> tuple:
        if not self._visible:
            return (False, "", "", None, (), ())
        player = _get_player()
        if player is None:
            return (False, "", "", None, (), ())
        name = player.GetName() if hasattr(player, "GetName") else ""
        species_key = _species_key_for(player)
        speed_label = _speed_label_for(player, self._player_control)
        icons_frozen = _frozen_icon_descriptors(player)
        config_frozen = _frozen_config(player, self._settings_open)
        return (True, name, speed_label, species_key, icons_frozen, config_frozen)

    # ── Panel framework ─────────────────────────────────────────────────
    def render_payload(self) -> Optional[str]:
        snap = self._snapshot()
        if snap == self._last_snapshot:
            return None
        self._last_snapshot = snap
        visible, ship_name, speed_label, species_key, _icons_frozen, _config_frozen = snap
        player = _get_player() if visible else None
        payload = {
            "visible": visible,
            "ship_name": ship_name,
            "speed_label": speed_label,
            "silhouette_url": ship_icons.icon_path_for_species(species_key or ""),
            "weapon_icons": list(_resolve_icon_descriptors(player)),
            "config": _config_payload(player, self._settings_open),
        }
        return "setWeaponsDisplay(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        # toggle-view is pure panel-local UI state (works even with no player).
        if action == "toggle-view":
            self._settings_open = not self._settings_open
            self.invalidate()
            return True
        handler_name = _CONFIG_ACTIONS.get(action)
        if handler_name is None:
            return False
        player = _get_player()
        if player is None:
            return False
        getattr(weapon_config, handler_name)(player)
        self.invalidate()
        return True

    def invalidate(self) -> None:
        self._last_snapshot = None


# ── Helpers ─────────────────────────────────────────────────────────────

def _get_player():
    try:
        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        return game.GetPlayer() if game is not None else None
    except Exception:
        return None


def _speed_label_for(ship, player_control) -> str:
    """Returns the header speed readout in BC's helm-tooltip format.

    Mirrors ``BridgeHandlers.HelmUpdateToolTip`` at
    ``sdk/.../BridgeHandlers.py:1389-1396``:

    * impulse — 0-9 throttle notch (BC quantises ``GetImpulse() * 9``
      with a +0.1 round-half-up nudge; we read the equivalent value
      straight off ``_PlayerControl.impulse_level``, which the host
      loop drives directly from the throttle keys).
    * velocity — ``int(|velocity| * GUPS_TO_KPH)``.
    * label — ``"Speed {impulse} : {velocity} kph"`` (the bare
      ``"Speed"`` and ``"kph"`` strings come from
      ``data/TGL/Bridge Menus.tgl`` in stock BC).

    ``_PlayerControl`` carries the source of truth for both readings under
    manual flight: ``impulse_level`` (-2..9 signed; a negative level is
    reverse and shows as ``R``) and ``_current_speed`` (the integrated GU/s
    value the ship-motion step applies each frame). When a helm AI owns the
    ship (``ship.GetAI()`` non-None — Orbit Planet, All Stop, ...),
    ``_current_speed`` is parked at its handoff value and the AI drives the
    ship through ``_step_ship_motion``, so the velocity reading comes from
    the ship's real published velocity instead. Fall back to the ship's own
    velocity too if the panel is constructed without the control hook
    (e.g. unit tests).
    """
    def _ship_velocity_gups(s) -> float:
        if s is None or not hasattr(s, "GetVelocity"):
            return 0.0
        try:
            v = s.GetVelocity()
            return (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5
        except Exception:
            return 0.0

    if player_control is not None:
        impulse = int(getattr(player_control, "impulse_level", 0) or 0)
        under_ai = False
        if ship is not None:
            get_ai = getattr(type(ship), "GetAI", None)
            under_ai = callable(get_ai) and ship.GetAI() is not None
        if under_ai:
            velocity_gups = _ship_velocity_gups(ship)
        else:
            velocity_gups = float(getattr(player_control, "_current_speed", 0.0) or 0.0)
    else:
        impulse = 0
        velocity_gups = _ship_velocity_gups(ship)

    # Negative throttle is reverse — show "R" rather than the signed notch.
    impulse_str = "R" if impulse < 0 else str(impulse)
    velocity_kph = int(abs(velocity_gups) * GUPS_TO_KPH)
    return "Speed " + impulse_str + " : " + str(velocity_kph) + " kph"


def _species_key_for(ship) -> str:
    """Return the ship-icon filename stem (e.g. ``Galaxy``) for the
    ship's species, or ``""`` if no icon is registered."""
    try:
        if not hasattr(ship, "GetSpecies"):
            return ""
        species_int = ship.GetSpecies()
        if not isinstance(species_int, int):
            return ""
        stem = stem_for_species(species_int)
        return stem if stem else ""
    except Exception:
        return ""


def _has_charge_model(mount) -> bool:
    """True when the mount carries an energy-weapon charge reservoir.

    PhaserBank / PulseWeapon / TractorBeam inherit a charge model from
    EnergyWeaponProperty (max_charge > 0). TorpedoTube also inherits
    GetChargePercentage from the shared ShipSubsystem hierarchy, but
    its ``_max_charge`` is 0 and the method returns 0 — the tube's
    "ready to fire" state is timer-driven via the reload delay
    instead. Predicate on max_charge so the descriptor routes tubes
    through the reload-based ratio below.
    """
    if not hasattr(mount, "GetMaxCharge"):
        return False
    try:
        return float(mount.GetMaxCharge()) > 0.0
    except Exception:
        return False


def _has_reload_model(mount) -> bool:
    """True when the mount tracks discrete reload state — torpedo
    tubes, mainly. ``GetMaxReady`` returning a positive int signals
    a queue-based ammo model with timer reloads."""
    if not hasattr(mount, "GetMaxReady"):
        return False
    try:
        return int(mount.GetMaxReady()) > 0
    except Exception:
        return False


def _reload_ratio(tube) -> float:
    """Binary ready / not-ready state for a torpedo tube.

    BC's tube model is discrete — the tube either has a queued round
    or it doesn't. There's no canonical "75 % reloaded" colour state.
    Loaded reads at 1.0 (palette-100, BC fill green); empty reads at
    0.3 (palette-30, BC g_kSubsystemEmptyColor red) — not 0.0 (which
    is the palette's pure-black stop reserved for fully discharged
    energy weapons). Torpedoes don't "go dark"; they're either ready
    or reloading, and BC's HUD shows both states in the same red the
    energy banks use at their fire threshold.
    """
    try:
        return 1.0 if int(tube.GetNumReady()) > 0 else 0.3
    except Exception:
        return 1.0


def _bank_targets_in_solution(bank, ship, target) -> bool:
    """True iff ``target`` sits inside ``bank``'s firing arc AND
    within the global phaser fire range. This is BC's "in arc"
    indicator semantics — the visual cue lights up whenever you
    *could* fire on the target, regardless of charge state or
    whether you're actually pulling the trigger.

    Reuses the same arc-gate code as the combat dispatcher
    (engine/appc/subsystems.py:_emitter_in_arc) so the panel
    visualisation can't disagree with the firing logic.
    """
    if bank is None or ship is None or target is None:
        return False
    if not (hasattr(ship, "GetWorldLocation")
            and hasattr(target, "GetWorldLocation")):
        return False
    from engine.appc.subsystems import (
        PHASER_MAX_RANGE_GU,
        _emitter_in_arc,
        _resolve_bank_aim_world,
    )
    sp = ship.GetWorldLocation()
    tp = target.GetWorldLocation()
    dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
    if dx * dx + dy * dy + dz * dz > PHASER_MAX_RANGE_GU * PHASER_MAX_RANGE_GU:
        return False
    aim = _resolve_bank_aim_world(bank, target)
    return _emitter_in_arc(bank, ship, aim)


def _icon_descriptor_for_mount(mount, ship=None, target=None):
    """Returns the descriptor dict for a single mount, or None when
    the mount has no icon (icon_num=0 sentinel) or its icon number is
    not in the tracer registry."""
    if mount is None or not hasattr(mount, "GetIconNum"):
        return None
    icon_num = mount.GetIconNum()
    if not isinstance(icon_num, int) or icon_num == 0:
        return None
    icon_svg = weapon_icons.icon_svg_for_num(icon_num)
    if icon_svg is None:
        return None
    x_px = float(mount.GetIconPositionX()) if hasattr(mount, "GetIconPositionX") else 0.0
    y_px = float(mount.GetIconPositionY()) if hasattr(mount, "GetIconPositionY") else 0.0
    above = bool(mount.IsIconAboveShip()) if hasattr(mount, "IsIconAboveShip") else False
    firing = bool(mount.IsFiring()) if hasattr(mount, "IsFiring") else False
    destroyed = bool(mount.IsDestroyed()) if hasattr(mount, "IsDestroyed") else False

    # Power state for colour theming. A bank is "online" when its
    # parent weapon system has power (PoweredSubsystem.IsOn) and the
    # bank itself isn't destroyed. Charge ratio (0..1) drives the
    # red → green colour lerp on the icon. Torpedo tubes have no
    # charge model (they reload on a timer) — treat them as fully
    # ready when online so the icon reads at the BC "Full" colour.
    parent = mount.GetParentSubsystem() if hasattr(mount, "GetParentSubsystem") else None
    online = (parent is not None
              and hasattr(parent, "IsOn") and bool(parent.IsOn())
              and not destroyed)
    if online and _has_charge_model(mount):
        try:
            charge_ratio = float(mount.GetChargePercentage())
        except Exception:
            charge_ratio = 1.0
    elif online and _has_reload_model(mount):
        charge_ratio = _reload_ratio(mount)
    elif online:
        charge_ratio = 1.0
    else:
        charge_ratio = 0.0
    charge_ratio = max(0.0, min(1.0, charge_ratio))

    # "In firing solution" — true when the bank can hit the player's
    # target right now (in arc + in range). Drives a fine white
    # stroke around the arc shape via CSS, replacing the SDK's
    # separate field-overlay icons (500-515). Energy weapons only —
    # torpedo tubes don't have a meaningful arc gate in BC.
    in_firing_arc = (
        _has_charge_model(mount)
        and _bank_targets_in_solution(mount, ship, target)
    )

    return {
        "icon_num": icon_num,
        "icon_svg": icon_svg,
        "x_px": x_px,
        "y_px": y_px,
        "above": above,
        "firing": firing,
        "destroyed": destroyed,
        "online": online,
        "charge_ratio": charge_ratio,
        "in_firing_arc": in_firing_arc,
    }


def _resolve_icon_descriptors(ship) -> tuple:
    """Walk the ship's phaser, pulse-weapon, and torpedo systems and
    emit one descriptor per mount with a registered icon. The ship's
    current target gets passed through to the per-mount builder so
    each phaser bank can report whether the target sits in its arc."""
    if ship is None:
        return ()
    target = ship.GetTarget() if hasattr(ship, "GetTarget") else None
    out: list[dict] = []
    for getter_name in _ICON_SOURCE_SYSTEMS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        try:
            system = getter()
        except Exception:
            continue
        if system is None:
            continue
        try:
            n = system.GetNumChildSubsystems()
        except Exception:
            continue
        for i in range(n):
            try:
                mount = system.GetChildSubsystem(i)
            except Exception:
                continue
            desc = _icon_descriptor_for_mount(mount, ship=ship, target=target)
            if desc is not None:
                out.append(desc)
    return tuple(out)


def _config_payload(ship, settings_open: bool) -> dict:
    """The weapon-config block sent to JS: the shared snapshot plus the
    panel-local open/closed state of the settings view."""
    cfg = dict(weapon_config.read_weapon_config(ship))
    cfg["show_settings"] = bool(settings_open)
    return cfg


def _frozen_config(ship, settings_open: bool) -> tuple:
    """Hashable form of the config block for snapshot equality — mirrors
    _frozen_icon_descriptors so a config change (type/spread/intensity/toggle
    or opening the settings view) re-emits the payload, and steady state does
    not."""
    cfg = _config_payload(ship, settings_open)
    return (
        cfg["show_settings"],
        cfg["has_any_config"],
        cfg["has_torpedoes"], cfg["torp_type"], cfg["torp_count"],
        cfg["torp_types_cyclable"], cfg["spread"], tuple(cfg["spread_options"]),
        cfg["has_phasers"], cfg["phaser_intensity"],
        cfg["tractor_present"], cfg["tractor_on"],
        cfg["cloak_present"], cfg["cloak_on"],
    )


def _frozen_icon_descriptors(ship) -> tuple:
    """Hashable form of the descriptor list for snapshot equality.

    Each descriptor collapses into a flat tuple so snapshot equality
    picks up firing/destroyed/online/charge/in-arc flips without
    storing dicts. Charge is bucketed to 10% so a steady recharge or
    discharge doesn't re-emit the JSON payload every tick — the JS
    colour lerp still uses the full-precision ratio from the payload,
    but the bucket gates whether we send a new payload at all.
    """
    frozen: list[tuple] = []
    for d in _resolve_icon_descriptors(ship):
        charge_bucket = int(round(d["charge_ratio"] * 10))
        frozen.append((
            d["icon_num"], d["x_px"], d["y_px"],
            d["above"], d["firing"], d["destroyed"],
            d["online"], charge_bucket, d["in_firing_arc"],
        ))
    return tuple(frozen)
