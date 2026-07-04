"""Engine-owned hardpoint-template overrides for stock ships.

Why: we extend stock ships' hardpoint data (baked glow regions today; placement
tweaks tomorrow) without editing sdk/Build/scripts/. The SDK hardpoint file
registers its templates as authored, then `apply(leaf)` runs as a second pass
from the SDK-loader hook (see engine/appc/sdk_overrides.py) — including after
loadspacehelper's ClearLocalTemplates() -> reload(mod), before LoadPropertySet,
so overrides always land on the freshly registered templates.

Authoring convention: one commented section per ship, as a `_<leaf>` function
keyed in OVERRIDES by the hardpoint module leaf name (lowercase, e.g.
"galaxy"). Sections receive a None-safe `find(name)` for LOCAL_TEMPLATES lookup
and must guard every template (`if p is not None`) — a template can be renamed
or absent in a modified install and the section must still complete.

Glow-region schema (consumed by the future baked-glow ShipGlowController pass;
same schema modders can put directly in hardpoint files behind a
`hasattr(P, "SetGlowRegionShape")` guard — see README "Information for
modders"):

    P.SetGlowRegionShape(i, "Sphere" | "Cylinder" | "Box")
    P.SetGlowRegionPosition(i, x, y, z)   # body-frame game units
    P.SetGlowRegionAxis(i, x, y, z)       # Cylinder only
    P.SetGlowRegionRadius(i, r)           # Sphere / Cylinder
    P.SetGlowRegionExtent(i, aft, fore)   # Cylinder only, along axis
    P.SetGlowRegionScale(i, sx, sy, sz)   # Box only: half-extents

Data-bag read-back quirk: TGModelProperty stores Set<F>(*args) under key
(F, args[:-1]) with value args[-1], so multi-arg setters are read back either
via prop._data or by passing the same leading args (e.g.
GetGlowRegionExtent(0, -2.0) -> 2.0). GetGlowRegionShape(i) works directly.

Known gap: a project-root shadow hardpoint (none exist today — the last one,
ships/Hardpoints/sovereign.py, was replaced by this file's sovereign section)
would load through the normal import machinery, not _SDKLoader, so the hook
would not fire for it. Prefer an override section here over a shadow; if a
shadow is ever unavoidable, it must call
`engine.appc.hardpoint_overrides.apply("<leaf>")` itself at module bottom.
"""


def apply(leaf: str) -> None:
    """Run the override section for a hardpoint module leaf name, if any."""
    fn = OVERRIDES.get(leaf)
    if fn is None:
        return
    import App

    mgr = App.g_kModelPropertyManager

    def find(name):
        return mgr.FindByName(name, App.TGModelPropertyManager.LOCAL_TEMPLATES)

    fn(find)


############################################
# galaxy — Galaxy class (baked glow regions)
############################################

def _galaxy(find):
    # Warp nacelles: cylinders along model +Y through the nacelle hardpoints.
    for name in ("Port Warp", "Star Warp"):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, 0.45)
            p.SetGlowRegionExtent(0, -2.0, 2.0)

    # Impulse vents: baked cylinders matching the runtime defaults (centre
    # defaults to the hardpoint position, running aft for 2 GU). Starting
    # point for hand-tuning — e.g. swap a vent to a Box once Box rendering
    # lands.
    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
        ("Center Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

    sa = find("Sensor Array")
    if sa is not None:
        sa.SetGlowRegionShape(0, "Sphere")
        sa.SetGlowRegionPosition(0, 0.0, -0.45, -0.50)
        sa.SetGlowRegionRadius(0, 0.28)


############################################
# GenericTemplate — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _GenericTemplate(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp Engine", 0.0938, -0.7812, 0.7812),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse Engine", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# akira — baked impulse glow (tools/bake_impulse_glow.py)
#         + hull-conforming shield silhouette
############################################

def _akira(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.23),
        ("Star Impulse", 0.23),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

    # Dauntless extension: hull-conforming shield silhouette (engine/shields.py
    # -> shield_pass.cc). Stock BC's Appc treats SetSkinShielding as a no-op.
    sg = find("Shield Generator")
    if sg is not None:
        sg.SetSkinShielding(1)

############################################
# ambassador — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _ambassador(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.3, -2.5, 2.5),
        ("Star Warp", 0.3, -2.5, 2.5),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.3),
        ("Star Impulse", 0.3),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# birdofprey — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _birdofprey(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.0638, -0.5312, 0.5312),
        ("Star Warp", 0.0638, -0.5312, 0.5312),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse Engine", 0.15),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# bombfreighter — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _bombfreighter(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp", 0.2625, -2.1875, 2.1875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.2),
        ("Star Impulse", 0.2),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# cardfreighter — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _cardfreighter(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp", 0.2625, -2.1875, 2.1875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.2),
        ("Star Impulse", 0.2),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# cardhybrid — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _cardhybrid(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.525, -4.375, 4.375),
        ("Star Warp", 0.525, -4.375, 4.375),
        ("Center Warp", 0.45, -3.75, 3.75),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.3),
        ("Star Impulse", 0.3),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# commarray — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _commarray(find):
    for name, radius in (
        ("Impulse", 2.0),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# commlight — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _commlight(find):
    for name, radius in (
        ("Impulse", 0.5),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# e2m0warbird — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _e2m0warbird(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.7),
        ("Star Impulse", 0.7),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# enterprise — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _enterprise(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# escapepod — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _escapepod(find):
    for name, radius in (
        ("Port Impulse", 0.02),
        ("Star Impulse", 0.02),
        ("Center Impulse", 0.02),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# freighter — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _freighter(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp Engine", 0.1875, -1.5625, 1.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.4),
        ("Star Impulse", 0.4),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# galor — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _galor(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp Engine 1", 0.1875, -1.5625, 1.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.2),
        ("Star Impulse", 0.2),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# geronimo — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _geronimo(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.23),
        ("Star Impulse", 0.23),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# keldon — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _keldon(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp Engine 1", 0.1875, -1.5625, 1.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Engine 1", 0.3),
        ("Engine 2", 0.3),
        ("Engine 3", 0.25),
        ("Engine 4", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# kessokheavy — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _kessokheavy(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Star Warp", 0.9375, -7.8125, 7.8125),
        ("Port Warp", 0.9375, -7.8125, 7.8125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 1.2),
        ("Star Impulse", 1.2),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# kessoklight — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _kessoklight(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# kessokmine — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _kessokmine(find):
    for name, radius in (
        ("Impulse Engine 1", 0.17),
        ("Impulse Engine 2", 0.17),
        ("Impulse Engine 3", 0.17),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# marauder — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _marauder(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Star Warp", 0.225, -1.875, 1.875),
        ("Port Warp", 0.225, -1.875, 1.875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Star Impulse", 0.12),
        ("Port Impulse", 0.12),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# matankeldon — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _matankeldon(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp Engine 1", 0.1875, -1.5625, 1.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Engine 1", 0.3),
        ("Engine 2", 0.3),
        ("Engine 3", 0.25),
        ("Engine 4", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# nebula — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _nebula(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.2063, -1.7188, 1.7188),
        ("Star Warp", 0.2063, -1.7188, 1.7188),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.3),
        ("Star Impulse", 0.3),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# peregrine — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _peregrine(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.1875, -1.5625, 1.5625),
        ("Star Warp", 0.1875, -1.5625, 1.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# probe — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _probe(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp", 0.0094, -0.0781, 0.0781),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse", 0.02),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# probe2 — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _probe2(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp", 0.0094, -0.0781, 0.0781),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse", 0.02),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# rankuf — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _rankuf(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.0638, -0.5312, 0.5312),
        ("Star Warp", 0.0638, -0.5312, 0.5312),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse Engine", 0.15),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# shuttle — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _shuttle(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.0112, -0.0938, 0.0938),
        ("Star Warp", 0.0112, -0.0938, 0.0938),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.03),
        ("Star Impulse", 0.03),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# sovereign — baked impulse glow (tools/bake_impulse_glow.py)
#             + hull-conforming shield silhouette (was the deleted
#             ships/Hardpoints/sovereign.py root-shadow fork, b743949c)
############################################

def _sovereign(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.375, -3.125, 3.125),
        ("Star Warp", 0.375, -3.125, 3.125),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

    # Dauntless extension: hull-conforming shield silhouette (engine/shields.py
    # -> shield_pass.cc). Stock BC's Appc treats SetSkinShielding as a no-op.
    sg = find("Shield Generator")
    if sg is not None:
        sg.SetSkinShielding(1)

############################################
# sunbuster — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _sunbuster(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Warp 1", 0.7875, -6.5625, 6.5625),
        ("Warp 2", 0.7875, -6.5625, 6.5625),
        ("Warp 3", 0.7875, -6.5625, 6.5625),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Impulse 1", 1.2),
        ("Impulse 2", 1.2),
        ("Impulse 3", 1.2),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# transport — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _transport(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.225, -1.875, 1.875),
        ("Star Warp", 0.225, -1.875, 1.875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# vorcha — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _vorcha(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.225, -1.875, 1.875),
        ("Star Warp", 0.225, -1.875, 1.875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.25),
        ("Star Impulse", 0.25),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

############################################
# warbird — baked impulse glow (tools/bake_impulse_glow.py)
############################################

def _warbird(find):
    # Warp glow: formula starting point (0.375*R radius,
    # +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune per nacelle.
    for name, radius, aft, fore in (
        ("Port Warp", 0.5625, -4.6875, 4.6875),
        ("Star Warp", 0.5625, -4.6875, 4.6875),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, aft, fore)

    for name, radius in (
        ("Port Impulse", 0.23),
        ("Star Impulse", 0.23),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
            p.SetGlowRegionRadius(0, radius)
            p.SetGlowRegionExtent(0, 0.0, 2.0)

OVERRIDES = {
    "galaxy": _galaxy,
    "GenericTemplate": _GenericTemplate,
    "akira": _akira,
    "ambassador": _ambassador,
    "birdofprey": _birdofprey,
    "bombfreighter": _bombfreighter,
    "cardfreighter": _cardfreighter,
    "cardhybrid": _cardhybrid,
    "commarray": _commarray,
    "commlight": _commlight,
    "e2m0warbird": _e2m0warbird,
    "enterprise": _enterprise,
    "escapepod": _escapepod,
    "freighter": _freighter,
    "galor": _galor,
    "geronimo": _geronimo,
    "keldon": _keldon,
    "kessokheavy": _kessokheavy,
    "kessoklight": _kessoklight,
    "kessokmine": _kessokmine,
    "marauder": _marauder,
    "matankeldon": _matankeldon,
    "nebula": _nebula,
    "peregrine": _peregrine,
    "probe": _probe,
    "probe2": _probe2,
    "rankuf": _rankuf,
    "shuttle": _shuttle,
    "sovereign": _sovereign,
    "sunbuster": _sunbuster,
    "transport": _transport,
    "vorcha": _vorcha,
    "warbird": _warbird,
}
