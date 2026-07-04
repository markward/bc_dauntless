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

Known gap: project-root shadow hardpoints (e.g. ships/Hardpoints/sovereign.py)
load through the normal import machinery, not _SDKLoader, so the hook does not
fire for them. A shadow that needs overrides calls
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

    # Impulse vents: boxes shifted ~0.8 GU aft of the hardpoint so the volume
    # trails the exhaust.
    for name, pos in (
        ("Port Impulse", (-1.22, -1.00, 0.32)),
        ("Star Impulse", (1.22, -1.00, 0.32)),
        ("Center Impulse", (0.00, -1.90, -0.08)),
    ):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Box")
            p.SetGlowRegionPosition(0, pos[0], pos[1], pos[2])
            p.SetGlowRegionScale(0, 0.30, 1.00, 0.12)

    sa = find("Sensor Array")
    if sa is not None:
        sa.SetGlowRegionShape(0, "Sphere")
        sa.SetGlowRegionPosition(0, 0.0, -0.45, -0.50)
        sa.SetGlowRegionRadius(0, 0.28)


OVERRIDES = {
    "galaxy": _galaxy,
}
