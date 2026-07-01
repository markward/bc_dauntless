"""Surface-agnostic read + mutate helpers for the player's weapon configuration.

Single source of truth for the weapon-settings controls (torpedo type / spread,
phaser intensity, tractor + cloak toggles).  The weapons HUD panel drives these
today; a future F2 tactical-menu surface calls the same helpers so both stay in
sync — toggling cloak from one surface is reflected in the other next tick.

Everything here is raise-safe: a ship missing a subsystem is a silent no-op on
mutation and an absent flag on read.  All functions take the player ship (which
may be ``None``).
"""
from __future__ import annotations

from engine.appc.subsystems import PhaserSystem


# ── Subsystem lookups (raise-safe) ───────────────────────────────────────────

def _get(ship, getter_name):
    if ship is None:
        return None
    getter = getattr(ship, getter_name, None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _torpedo_system(ship):
    sys = _get(ship, "GetTorpedoSystem")
    return sys if _num_weapons(sys) > 0 else None


def _phaser_system(ship):
    sys = _get(ship, "GetPhaserSystem")
    return sys if _num_weapons(sys) > 0 else None


def _tractor_system(ship):
    # The ships factory hands every hull a default-empty TractorBeamSystem;
    # a tractor is only "equipped" when it actually has ≥1 emitter.
    sys = _get(ship, "GetTractorBeamSystem")
    return sys if _num_weapons(sys) > 0 else None


def _cloak_subsystem(ship):
    return _get(ship, "GetCloakingSubsystem")


def _num_weapons(system) -> int:
    """Number of launchers/banks on a weapon system (0 when absent)."""
    if system is None:
        return 0
    for name in ("GetNumWeapons", "GetNumChildSubsystems"):
        getter = getattr(system, name, None)
        if getter is None:
            continue
        try:
            n = getter()
        except Exception:
            continue
        if isinstance(n, int):
            return n
    return 0


# ── Read ─────────────────────────────────────────────────────────────────────

def read_weapon_config(ship) -> dict:
    """Return the full weapon-config snapshot for ``ship``.

    See the module / spec for the field contract.  Absent subsystems yield
    ``False`` presence flags and neutral defaults.
    """
    torps = _torpedo_system(ship)
    has_torpedoes = torps is not None
    torp_type = ""
    torp_count = 0
    torp_types_cyclable = False
    spread = 1
    spread_options = [1]
    if has_torpedoes:
        ammo = torps.GetCurrentAmmoType() if hasattr(torps, "GetCurrentAmmoType") else None
        if ammo is not None and hasattr(ammo, "GetAmmoName"):
            try:
                torp_type = ammo.GetAmmoName() or ""
            except Exception:
                torp_type = ""
        torp_count = _torpedo_count(torps)
        try:
            torp_types_cyclable = torps.GetNumAmmoTypes() > 1
        except Exception:
            torp_types_cyclable = False
        try:
            spread = int(torps.GetSpread())
        except Exception:
            spread = 1
        try:
            spread_options = list(torps.GetSpreadOptions())
        except Exception:
            spread_options = [1]

    phasers = _phaser_system(ship)
    has_phasers = phasers is not None
    phaser_intensity = "Full"
    if has_phasers:
        try:
            if phasers.GetPowerLevel() == PhaserSystem.PP_LOW:
                phaser_intensity = "Light"
        except Exception:
            phaser_intensity = "Full"

    tractor = _tractor_system(ship)
    tractor_present = tractor is not None
    tractor_on = False
    if tractor_present:
        try:
            # The toggle reflects the persistent ENGAGE intent (IsEngaged),
            # NOT the instantaneous IsFiring beam state — it stays "On" even
            # when the beam momentarily isn't gripping (out of range / shields).
            tractor_on = bool(tractor.IsEngaged())
        except Exception:
            tractor_on = False

    cloak = _cloak_subsystem(ship)
    cloak_present = cloak is not None
    cloak_on = False
    if cloak_present:
        try:
            cloak_on = bool(cloak.IsTryingToCloak())
        except Exception:
            cloak_on = False

    has_any_config = (has_torpedoes or has_phasers
                      or tractor_present or cloak_present)

    return {
        "has_torpedoes": has_torpedoes,
        "torp_type": torp_type,
        "torp_count": torp_count,
        "torp_types_cyclable": torp_types_cyclable,
        "spread": spread,
        "spread_options": spread_options,
        "has_phasers": has_phasers,
        "phaser_intensity": phaser_intensity,
        "tractor_present": tractor_present,
        "tractor_on": tractor_on,
        "cloak_present": cloak_present,
        "cloak_on": cloak_on,
        "has_any_config": has_any_config,
    }


def _torpedo_count(torps) -> int:
    """Total ready rounds across all tubes."""
    total = 0
    n = _num_weapons(torps)
    for i in range(n):
        tube = torps.GetWeapon(i) if hasattr(torps, "GetWeapon") else None
        if tube is None or not hasattr(tube, "GetNumReady"):
            continue
        try:
            total += int(tube.GetNumReady())
        except Exception:
            continue
    return total


# ── Mutate ───────────────────────────────────────────────────────────────────

def cycle_torpedo_type(ship) -> None:
    """Advance the selected torpedo ammo type to the next loaded slot (wraps).
    No-op with ≤1 type or no torpedo system."""
    torps = _torpedo_system(ship)
    if torps is None or not hasattr(torps, "CycleAmmoType"):
        return
    try:
        torps.CycleAmmoType()
    except Exception:
        pass


def cycle_torpedo_spread(ship) -> None:
    """Advance the torpedo spread to the next available option (wraps).
    No-op with ≤1 option or no torpedo system."""
    torps = _torpedo_system(ship)
    if torps is None:
        return
    try:
        options = list(torps.GetSpreadOptions())
        if len(options) <= 1:
            return
        current = int(torps.GetSpread())
        try:
            idx = options.index(current)
        except ValueError:
            idx = 0
        torps.SetSpread(options[(idx + 1) % len(options)])
    except Exception:
        pass


def toggle_phaser_intensity(ship) -> None:
    """Flip phaser power level between PP_HIGH (Full) and PP_LOW (Light)."""
    phasers = _phaser_system(ship)
    if phasers is None:
        return
    try:
        if phasers.GetPowerLevel() == PhaserSystem.PP_LOW:
            phasers.SetPowerLevel(PhaserSystem.PP_HIGH)
        else:
            phasers.SetPowerLevel(PhaserSystem.PP_LOW)
    except Exception:
        pass


def toggle_tractor(ship) -> None:
    """Engage / disengage the tractor beam.  Engaging fires on the ship's
    current target (the tractor's StartFiring is a no-op without one)."""
    tractor = _tractor_system(ship)
    if tractor is None:
        return
    try:
        # Toggle the persistent ENGAGE intent (not the instantaneous beam):
        # engaged → disengage; otherwise engage on the current target (the
        # tractor's StartFiring is a no-op without one).
        if tractor.IsEngaged():
            tractor.StopFiring()
        else:
            target = ship.GetTarget() if hasattr(ship, "GetTarget") else None
            tractor.StartFiring(target, None)
    except Exception:
        pass


def toggle_cloak(ship) -> None:
    """Engage / disengage the cloaking device."""
    cloak = _cloak_subsystem(ship)
    if cloak is None:
        return
    try:
        if cloak.IsTryingToCloak():
            cloak.StopCloaking()
        else:
            cloak.StartCloaking()
    except Exception:
        pass
