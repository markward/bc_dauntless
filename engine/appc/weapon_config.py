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
    torp_types: list[str] = []
    torp_types_cyclable = False
    # BC's tactical "torpedo spread" toggle IS the firing-chain selector
    # (WeaponSystem::SetFiringChainMode — audited §2.10, no tube-count
    # parameter exists anywhere in BC).  Labels come straight from the
    # hardpoint's authored FiringChainString; 67 of 70 stock hardpoints
    # author none, so spread == "" / spread_options == [] and the panel
    # hides the control.
    spread = ""
    spread_options: list[str] = []
    if has_torpedoes:
        ammo = torps.GetCurrentAmmoType() if hasattr(torps, "GetCurrentAmmoType") else None
        if ammo is not None and hasattr(ammo, "GetAmmoName"):
            try:
                torp_type = ammo.GetAmmoName() or ""
            except Exception:
                torp_type = ""
        torp_count = _torpedo_count(torps)
        # The live ammo model IS the menu: after the SDK curates it
        # (QuickBattle.RemoveAmmoType prunes PhasedPlasma), the distinct
        # GetAmmoName()s across the loaded slots are exactly the selectable
        # types — no string surgery, no UI-side filtering.  Cyclable when >1.
        torp_types = _distinct_torpedo_type_names(torps)
        torp_types_cyclable = len(torp_types) > 1
        chains = torps.GetFiringChains() if hasattr(torps, "GetFiringChains") else []
        spread_options = [label for (label, _groups) in chains]
        if spread_options:
            try:
                mode = int(torps.GetFiringChainMode())
            except Exception:
                mode = 0
            spread = spread_options[mode % len(spread_options)]

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
        "torp_types": torp_types,
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


def _distinct_torpedo_type_names(torps) -> list[str]:
    """Ordered, de-duplicated names of the SELECTABLE ammo types.

    Only types with rounds available count (BC gates on
    GetNumAvailableTorpsToType > 0 — AI/Preprocessors.py:537), so a
    declared-but-empty slot like PhasedPlasma (SetMaxTorpedoes 0) is excluded in
    missions as well as QuickBattle.  A hull may load the same type into several
    slots, so we dedupe by name while preserving slot order — the result is the
    exact set the player can cycle between (the "Type" control / F2 row)."""
    names: list[str] = []
    try:
        slots = torps.GetSelectableAmmoSlots()
    except Exception:
        return names
    for i in slots:
        try:
            ammo = torps.GetAmmoType(i)
            name = ammo.GetAmmoName() if ammo is not None else None
        except Exception:
            name = None
        if name and name not in names:
            names.append(name)
    return names


def _torpedo_count(torps) -> int:
    """Rounds of the SELECTED ammo type left in the magazine.

    BC keeps three tiers of torpedo state — stores (per type), tubes (loaded
    and ready), in flight — and the player-facing count is the STORES tier for
    the current type.  The SDK holds the two apart explicitly:
    TacticalCharacterHandlers.py:239-249 reports "we're out of torps of that
    type" on GetNumAvailableTorpsToType(GetAmmoTypeNumber()) <= 0, and only
    otherwise falls through to "we haven't reloaded yet" — the tube tier.

    Summing tube readiness instead conflates them: a Sovereign's 200 photons
    sit behind 6 single-round tubes, so it read 6 and never moved when the
    player switched type (both types share the same tubes).

    Legacy/test hulls whose hardpoint declares no magazine get our synthetic
    UNLIMITED type, which has no stores tier to report; those fall back to tube
    readiness so their readout is unchanged.
    """
    ammo = torps.GetCurrentAmmoType() if hasattr(torps, "GetCurrentAmmoType") else None
    if ammo is not None and not getattr(ammo, "_unlimited", False):
        try:
            return int(torps.GetNumAvailableTorpsToType(torps.GetCurrentAmmoSlot()))
        except Exception:
            return 0
    return _tube_ready_count(torps)


def _tube_ready_count(torps) -> int:
    """Total ready rounds across all tubes — BC's tube tier."""
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
    """Advance the torpedo firing chain (BC's tactical 'spread' toggle IS
    the chain selector — SetFiringChainMode; audited §2.10). Wraps; no-op
    when the hardpoint authors fewer than two chains."""
    torps = _torpedo_system(ship)
    if torps is None or not hasattr(torps, "GetFiringChains"):
        return
    try:
        n = len(torps.GetFiringChains())
        if n < 2:
            return
        torps.SetFiringChainMode((torps.GetFiringChainMode() + 1) % n)
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
