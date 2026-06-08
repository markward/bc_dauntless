"""Pure mappings for the persistent damage-decal store.

No host / renderer dependency: weapon type -> decal class, hull damage ->
decal intensity, and a guarded game-time reader. The C++ DamageDecalRing
owns the actual records (see native/src/scenegraph/damage_decals.*); this
module only computes the scalar inputs the emission path feeds to
host.damage_decal_add.
"""

# Mirror of scenegraph::WeaponClass (native/src/scenegraph/damage_decals.h).
WEAPON_CLASS_HEAT_GLOW = 0   # phaser — transient emissive bloom
WEAPON_CLASS_SCORCH = 1      # torpedo / disruptor — persistent deposit + ember

# Hull damage that maps to a full-intensity (1.0) decal. Tuning constant;
# spec §3.6 fixes only the contract (monotonic, clamped). Calibrated against
# the live renderer: per-tick phaser hull damage is ~0.28, so 8.0 gave ~3.5%
# intensity (invisible). 0.5 makes a single tick ~0.56 and a couple of merged
# ticks saturate to a clearly-visible glow; torpedoes saturate on one hit.
# Deliberately bold for visibility confirmation; dial up toward ~1-2 for subtlety.
INTENSITY_REFERENCE_DAMAGE = 0.5

# Visual-only radius multipliers per weapon class (gameplay r_hit unchanged).
# Calibrated against the live renderer: phaser glow reads better tight (0.5);
# torpedo scorch wants a broad deposit (3x the phaser scale) for the spread-B look.
_RADIUS_SCALE = {
    WEAPON_CLASS_HEAT_GLOW: 0.5,
    WEAPON_CLASS_SCORCH: 1.5,
}


def decal_radius_scale(weapon_class: int) -> float:
    """Visual-only radius multiplier for the given weapon class."""
    return _RADIUS_SCALE.get(weapon_class, 0.5)


def weapon_class_for(weapon_type):
    """Map a weapon_type string ("phaser" / "torpedo" / ...) to a decal class.

    Only "phaser" produces the transient heat-glow class; everything else
    (torpedo, disruptor, None, unknown) deposits persistent scorch.
    """
    if weapon_type == "phaser":
        return WEAPON_CLASS_HEAT_GLOW
    return WEAPON_CLASS_SCORCH


def decal_intensity(absorbed_hull: float) -> float:
    """Map hull damage actually dealt to a clamped [0,1] decal intensity.

    Monotonic in absorbed_hull, saturating at INTENSITY_REFERENCE_DAMAGE.
    """
    if absorbed_hull <= 0.0:
        return 0.0
    return min(1.0, float(absorbed_hull) / INTENSITY_REFERENCE_DAMAGE)


def _game_time_source() -> float:
    """Read the canonical game clock. Isolated so tests can monkeypatch it."""
    import App
    return float(App.g_kUtopiaModule.GetGameTime())


def current_game_time() -> float:
    """Game-time seconds for decal birth_time / aging, or 0.0 if unavailable.

    The decal clock must match the value passed to host.damage_decals_tick
    (host_loop uses the same App.g_kUtopiaModule.GetGameTime()).
    """
    try:
        return _game_time_source()
    except Exception:
        return 0.0
