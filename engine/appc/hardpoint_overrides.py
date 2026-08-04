"""Machine-owned hardpoint overrides — edited by the Ship Property Viewer.

Do NOT hand-edit: the SPV regenerates this file on save. One function per ship,
one block per subsystem, plain Appc setter calls.
Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md
"""


def apply(leaf):
    """Run a ship's override function from the SDK-loader hook, if any."""
    fn = OVERRIDES.get(leaf)
    if fn is None:
        return
    import App

    mgr = App.g_kModelPropertyManager

    def find(name):
        return mgr.FindByName(name, App.TGModelPropertyManager.LOCAL_TEMPLATES)

    fn(find)


def _galaxy(find):
    """galaxy."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -1.3, -1.9119627023044568, -0.06)
        p.SetGlowRegionScale(0, 0.30931014657993366, 1.307457336253744, 0.21014627531109478)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, -1.4575578162987863, -2.5553570421182474, -0.07330232818905524)
        p.SetLightEmitterRadius(0, 1.1305138134376325)
        p.SetLightEmitterColor(0, 0.14866794126015248, 0.4818838797813879, 1.0)
        p.SetLightEmitterIntensity(0, 1.61)
        p.SetLightEmitterAxis(0, 0.947510422865498, -0.014465973412098654, -0.319397454865385)
        p.SetLightEmitterLength(0, 2.0626169271513035)
        p.SetLightEmitterRadiusY(0, 3.4863760117016844)
        p.SetLightEmitterUp(0, 0.013530218187234225, 0.9998952073080984, -0.005148553010380573)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.3, -1.9119627023044568, -0.06)
        p.SetGlowRegionScale(0, 0.30931014657993366, 1.307457336253744, 0.21014627531109478)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -1.22, -0.31166273838979724, 0.32)
        p.SetGlowRegionScale(0, 0.15, 0.2, 0.05)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.22, -0.31166273838979724, 0.32)
        p.SetGlowRegionScale(0, 0.15, 0.2, 0.05)
    p = find("Center Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.0, -1.1, -0.08)
        p.SetGlowRegionScale(0, 0.2, 0.15, 0.1)
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.0, -0.29861956500569303, -0.5)
        p.SetGlowRegionScale(0, 0.5335676748872048, 0.19850541821587558, 0.15858130015119873)


def _GenericTemplate(find):
    """GenericTemplate."""
    p = find("Warp Engine")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0938)
        p.SetGlowRegionExtent(0, -0.7812, 0.7812)
    p = find("Impulse Engine")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _akira(find):
    """akira."""
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.17)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, -1.4, -0.8, -0.25)
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2604417052340165)
        p.SetGlowRegionExtent(0, -1.2589026527761655, 1.2589026527761655)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 1.4, -0.8, -0.25)
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2604417052340165)
        p.SetGlowRegionExtent(0, -1.2589026527761655, 1.2589026527761655)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Shield Generator")
    if p is not None:
        p.SetSkinShielding(1)


def _ambassador(find):
    """ambassador."""
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.4)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, -2.5, 2.5)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, -2.5, 2.5)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _birdofprey(find):
    """birdofprey."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0638)
        p.SetGlowRegionExtent(0, -0.5312, 0.5312)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0638)
        p.SetGlowRegionExtent(0, -0.5312, 0.5312)
    p = find("Impulse Engine")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.15)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _bombfreighter(find):
    """bombfreighter."""
    p = find("Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2625)
        p.SetGlowRegionExtent(0, -2.1875, 2.1875)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _cardfreighter(find):
    """cardfreighter."""
    p = find("Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2625)
        p.SetGlowRegionExtent(0, -2.1875, 2.1875)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _cardhybrid(find):
    """cardhybrid."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.525)
        p.SetGlowRegionExtent(0, -4.375, 4.375)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.525)
        p.SetGlowRegionExtent(0, -4.375, 4.375)
    p = find("Center Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.45)
        p.SetGlowRegionExtent(0, -3.75, 3.75)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _commarray(find):
    """commarray."""
    p = find("Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 2.0)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _commlight(find):
    """commlight."""
    p = find("Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.5)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _e2m0warbird(find):
    """e2m0warbird."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.7)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.7)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _enterprise(find):
    """enterprise."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _escapepod(find):
    """escapepod."""
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.02)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.02)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Center Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.02)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _freighter(find):
    """freighter."""
    p = find("Warp Engine")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.1875)
        p.SetGlowRegionExtent(0, -1.5625, 1.5625)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.4)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.4)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _galor(find):
    """galor."""
    return


def _geronimo(find):
    """geronimo."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _keldon(find):
    """keldon."""
    p = find("Warp Engine 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.1875)
        p.SetGlowRegionExtent(0, -1.5625, 1.5625)
    p = find("Engine 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 2")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 3")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 4")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _kessokheavy(find):
    """kessokheavy."""
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.9375)
        p.SetGlowRegionExtent(0, -7.8125, 7.8125)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.9375)
        p.SetGlowRegionExtent(0, -7.8125, 7.8125)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 1.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 1.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _kessoklight(find):
    """kessoklight."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.375)
        p.SetGlowRegionExtent(0, -3.125, 3.125)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _kessokmine(find):
    """kessokmine."""
    p = find("Impulse Engine 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.17)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Impulse Engine 2")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.17)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Impulse Engine 3")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.17)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _marauder(find):
    """marauder."""
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.12)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.12)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _matankeldon(find):
    """matankeldon."""
    p = find("Warp Engine 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.1875)
        p.SetGlowRegionExtent(0, -1.5625, 1.5625)
    p = find("Engine 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 2")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 3")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Engine 4")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _nebula(find):
    """nebula."""
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.25)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2063)
        p.SetGlowRegionExtent(0, -1.7188, 1.7188)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2063)
        p.SetGlowRegionExtent(0, -1.7188, 1.7188)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _peregrine(find):
    """peregrine."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.1875)
        p.SetGlowRegionExtent(0, -1.5625, 1.5625)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.1875)
        p.SetGlowRegionExtent(0, -1.5625, 1.5625)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _probe(find):
    """probe."""
    p = find("Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0094)
        p.SetGlowRegionExtent(0, -0.0781, 0.0781)
    p = find("Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.02)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _probe2(find):
    """probe2."""
    p = find("Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0094)
        p.SetGlowRegionExtent(0, -0.0781, 0.0781)
    p = find("Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.02)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _rankuf(find):
    """rankuf."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0638)
        p.SetGlowRegionExtent(0, -0.5312, 0.5312)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0638)
        p.SetGlowRegionExtent(0, -0.5312, 0.5312)
    p = find("Impulse Engine")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.15)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _shuttle(find):
    """shuttle."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0112)
        p.SetGlowRegionExtent(0, -0.0938, 0.0938)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.0112)
        p.SetGlowRegionExtent(0, -0.0938, 0.0938)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.03)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.03)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _sovereign(find):
    """sovereign."""
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 0.0, 0.9396087535954456, -0.24696981382993582)
        p.SetGlowRegionAxis(0, 0.0, -0.9421340682806745, 0.3352363306458675)
        p.SetGlowRegionRadius(0, 0.13739365178790047)
        p.SetGlowRegionExtent(0, 0.0, 0.1311633930862835)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.88, -1.9739079526646612, 0.15)
        p.SetGlowRegionScale(0, 0.25, 1.7903034577123764, 0.25)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.88, -1.9739079526646612, 0.15)
        p.SetGlowRegionScale(0, 0.25, 1.7903034577123764, 0.25)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.5753745771815283, 0.35131726699932136, 0.038309254535234594)
        p.SetGlowRegionScale(0, 0.2, 0.25, 0.07187231719672049)
        p.SetGlowRegionOrientation(0, 0.3006692546162243, 0.9303524952835365, 0.2098624164737968, -0.06453634079975354, -0.19969300078971072, 0.9777309272758936)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.5753745771815283, 0.35131726699932136, 0.038309254535234594)
        p.SetGlowRegionScale(0, 0.2, 0.25, 0.07187231719672049)
        p.SetGlowRegionOrientation(0, -0.3006692546162243, 0.9303524952835365, 0.2098624164737968, 0.06453634079975354, -0.19969300078971072, 0.9777309272758936)
    p = find("Shield Generator")
    if p is not None:
        p.SetSkinShielding(1)


def _sunbuster(find):
    """sunbuster."""
    p = find("Warp 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.7875)
        p.SetGlowRegionExtent(0, -6.5625, 6.5625)
    p = find("Warp 2")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.7875)
        p.SetGlowRegionExtent(0, -6.5625, 6.5625)
    p = find("Warp 3")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.7875)
        p.SetGlowRegionExtent(0, -6.5625, 6.5625)
    p = find("Impulse 1")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 1.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Impulse 2")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 1.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Impulse 3")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 1.2)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _transport(find):
    """transport."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _vorcha(find):
    """vorcha."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.875, 1.875)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _warbird(find):
    """warbird."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.5625)
        p.SetGlowRegionExtent(0, -4.6875, 4.6875)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.5625)
        p.SetGlowRegionExtent(0, -4.6875, 4.6875)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.23)
        p.SetGlowRegionExtent(0, 0.0, 2.0)


def _drydock(find):
    """drydock."""
    p = find("Hull")
    if p is not None:
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, -1.8829933930065075, -6.096608935851515, 2.1880006045545435)
        p.SetLightEmitterRadius(0, 1.0)
        p.SetLightEmitterColor(0, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(0, 1.0)
        p.SetLightEmitterAxis(0, -0.01303253787383479, -0.0020951957967578205, -0.9999128777604278)
        p.SetLightEmitterLength(0, 2.0)


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
    "drydock": _drydock,
}
