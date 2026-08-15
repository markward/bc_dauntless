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
        p.SetLightEmitterPosition(0, -1.3795797512029295, -2.255982854371039, -0.07330232818905524)
        p.SetLightEmitterRadius(0, 1.1305138134376325)
        p.SetLightEmitterColor(0, 0.14866794126015248, 0.4818838797813879, 1.0)
        p.SetLightEmitterIntensity(0, 1.11)
        p.SetLightEmitterAxis(0, 0.9971055372793476, -0.014465973412098654, -0.07464102853058888)
        p.SetLightEmitterLength(0, 1.3086745536782773)
        p.SetLightEmitterRadiusY(0, 3.4863760117016844)
        p.SetLightEmitterUp(0, 0.014384041311247434, 0.9998952073080984, -0.0016351629433147808)
        p.SetLightEmitterKind(1, "point")
        p.SetLightEmitterPosition(1, -1.3043241247498398, -0.7146049537779517, -0.060265834263955265)
        p.SetLightEmitterRadius(1, 1.4520315632375584)
        p.SetLightEmitterColor(1, 1.0, 0.0, 0.23685319782162306)
        p.SetLightEmitterIntensity(1, 0.25)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.3, -1.9119627023044568, -0.06)
        p.SetGlowRegionScale(0, 0.30931014657993366, 1.307457336253744, 0.21014627531109478)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 1.3795797512029295, -2.255982854371039, -0.07330232818905524)
        p.SetLightEmitterRadius(0, 1.1305138134376325)
        p.SetLightEmitterColor(0, 0.14866794126015248, 0.4818838797813879, 1.0)
        p.SetLightEmitterIntensity(0, 1.11)
        p.SetLightEmitterAxis(0, -0.9971055372793476, -0.014465973412098654, -0.07464102853058888)
        p.SetLightEmitterLength(0, 1.3086745536782773)
        p.SetLightEmitterRadiusY(0, 3.4863760117016844)
        p.SetLightEmitterUp(0, -0.014384041311247434, 0.9998952073080984, -0.0016351629433147808)
        p.SetLightEmitterKind(1, "point")
        p.SetLightEmitterPosition(1, 1.3043241247498398, -0.7146049537779517, -0.060265834263955265)
        p.SetLightEmitterRadius(1, 1.4520315632375584)
        p.SetLightEmitterColor(1, 1.0, 0.0, 0.23685319782162306)
        p.SetLightEmitterIntensity(1, 0.25)
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
        p.SetGlowRegionPosition(0, 0.0, -0.247236337851871, -0.5)
        p.SetGlowRegionScale(0, 0.5335676748872048, 0.19850541821587558, 0.1565580972394518)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 0.0, -0.7324181551442901, -0.5178831373759387)
        p.SetLightEmitterRadius(0, 2.5919160204046374)
        p.SetLightEmitterColor(0, 0.510321208791358, 0.7494499495146087, 1.0)
        p.SetLightEmitterIntensity(0, 2.75)
        p.SetLightEmitterAxis(0, 3.469446951953614e-16, 1.0, 0.0)
        p.SetLightEmitterLength(0, 2.0)
        p.SetLightEmitterRadiusY(0, 1.0)
        p.SetLightEmitterUp(0, 0.0, 0.0, 1.0)


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
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.0, 1.6594399956534711, -0.25)
        p.SetGlowRegionScale(0, 0.14124043170488845, 0.07079691539934439, 0.07141523534305927)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 0.0, 1.4213315435224074, -0.2778216516527464)
        p.SetLightEmitterRadius(0, 0.30000000000000004)
        p.SetLightEmitterColor(0, 0.7078473248529669, 0.8254988969736105, 1.0)
        p.SetLightEmitterIntensity(0, 2.0)
        p.SetLightEmitterAxis(0, 3.469446951953614e-16, 1.0, 0.0)
        p.SetLightEmitterLength(0, 1.9)
        p.SetLightEmitterRadiusY(0, 0.7)
        p.SetLightEmitterUp(0, 1.0, -3.469446951953614e-16, 0.0)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, -1.4, -0.7647607915585714, -0.25)
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2604417052340165)
        p.SetGlowRegionExtent(0, -1.2589026527761655, 1.2589026527761655)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, -1.3637335912961803, 0.1409297605246348, -0.25561975018734573)
        p.SetLightEmitterRadius(0, 1.0)
        p.SetLightEmitterColor(0, 1.0, 0.4729319868091467, 0.4603658775155296)
        p.SetLightEmitterIntensity(0, 2.25)
        p.SetLightEmitterAxis(0, 3.469446951953614e-16, 1.0, 0.0)
        p.SetLightEmitterLength(0, 1.258252275577203)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 1.4, -0.7647607915585714, -0.25)
        p.SetGlowRegionAxis(0, -0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.2604417052340165)
        p.SetGlowRegionExtent(0, -1.2589026527761655, 1.2589026527761655)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 1.3637335912961803, 0.1409297605246348, -0.25561975018734573)
        p.SetLightEmitterRadius(0, 1.0)
        p.SetLightEmitterColor(0, 1.0, 0.4729319868091467, 0.4603658775155296)
        p.SetLightEmitterIntensity(0, 2.25)
        p.SetLightEmitterAxis(0, -3.469446951953614e-16, 1.0, 0.0)
        p.SetLightEmitterLength(0, 1.258252275577203)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.96, 0.6828797110455359, -0.05)
        p.SetGlowRegionScale(0, 0.17803892234299573, 0.04311316788421988, 0.04277875352139736)
        p.SetGlowRegionOrientation(0, 0.7261573365587868, 0.687528561269893, 0.0, 0.0, 0.0, 1.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.96, 0.6828797110455359, -0.05)
        p.SetGlowRegionScale(0, 0.17803892234299573, 0.04311316788421988, 0.04277875352139736)
        p.SetGlowRegionOrientation(0, -0.7261573365587868, 0.687528561269893, 0.0, 0.0, 0.0, 1.0)
    p = find("Shield Generator")
    if p is not None:
        p.SetSkinShielding(1)


def _ambassador(find):
    """ambassador."""
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 0.0, 0.2884088383781463, -0.3672613386331434)
        p.SetGlowRegionAxis(0, 0.0, -0.9167388698405888, 0.3994869766630696)
        p.SetGlowRegionRadius(0, 0.27890322579841986)
        p.SetGlowRegionExtent(0, 0.0, 0.21370285093520475)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, -1.2, -1.8, 0.3)
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, -1.2259416887268986, 1.2259416887268986)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 1.2, -1.8, 0.3)
        p.SetGlowRegionAxis(0, -0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.3)
        p.SetGlowRegionExtent(0, -1.2259416887268986, 1.2259416887268986)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -1.0704943647077587, -0.24373511128921105, 0.4)
        p.SetGlowRegionScale(0, 0.11640947970758357, 0.09674786008673641, 0.08689860760152306)
        p.SetGlowRegionOrientation(0, 0.5866210275988871, 0.8098615745785361, 0.0, 0.0, 0.0, 1.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.0704943647077587, -0.24373511128921105, 0.4)
        p.SetGlowRegionScale(0, 0.11640947970758357, 0.09674786008673641, 0.08689860760152306)
        p.SetGlowRegionOrientation(0, -0.5866210275988871, 0.8098615745785361, 0.0, 0.0, 0.0, 1.0)


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
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.0, -0.5899387648717322, 0.03)
        p.SetGlowRegionScale(0, 0.1199065414319709, 0.08745161469251926, 0.08080578196746682)
        p.SetLightEmitterKind(0, "point")
        p.SetLightEmitterPosition(0, 0.0, -0.6269898730574315, 0.03695259794034239)
        p.SetLightEmitterRadius(0, 0.16520438239518337)
        p.SetLightEmitterColor(0, 1.0, 0.9834784963569925, 0.8447312668262376)
        p.SetLightEmitterIntensity(0, 1.0)
    p = find("Fwd Torpedo")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 0.0, 0.8572529294499402, -0.033764)
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.03134145990729312)
        p.SetGlowRegionExtent(0, 0.0, 0.09062154882729402)
        p.SetLightEmitterKind(0, "point")
        p.SetLightEmitterPosition(0, 0.0, 0.8197669984830285, -0.033764)
        p.SetLightEmitterRadius(0, 0.051763776534396094)
        p.SetLightEmitterColor(0, 1.0, 0.45809755461141033, 0.2607827284788081)
        p.SetLightEmitterIntensity(0, 2.0)


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
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 3.825687739664552, -0.5460723602660027, -1.0)
        p.SetGlowRegionScale(0, 0.7213271589653381, 3.10345555248113, 0.39812090722144466)
        p.SetLightEmitterKind(0, "strip")
        p.SetLightEmitterPosition(0, 3.8761773311501835, 0.7993125862583916, -1.2034194406928669)
        p.SetLightEmitterRadius(0, 2.9911357660563844)
        p.SetLightEmitterColor(0, 0.8732211168451325, 1.0, 0.3113441471558456)
        p.SetLightEmitterIntensity(0, 2.0)
        p.SetLightEmitterAxis(0, -0.0, -1.0, 0.0)
        p.SetLightEmitterLength(0, 4.025842994614761)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -3.825687739664552, -0.5460723602660027, -1.0)
        p.SetGlowRegionScale(0, 0.7213271589653381, 3.10345555248113, 0.39812090722144466)
        p.SetLightEmitterKind(0, "strip")
        p.SetLightEmitterPosition(0, -3.8761773311501835, 0.7993125862583916, -1.2034194406928669)
        p.SetLightEmitterRadius(0, 2.9911357660563844)
        p.SetLightEmitterColor(0, 0.8732211168451325, 1.0, 0.3113441471558456)
        p.SetLightEmitterIntensity(0, 2.0)
        p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
        p.SetLightEmitterLength(0, 4.025842994614761)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -1.3800116627338623, -6.042511953773285, 0.5)
        p.SetGlowRegionScale(0, 0.7138723001913112, 0.4573611686173884, 0.36527640941124423)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.3800116627338623, -6.042511953773285, 0.5)
        p.SetGlowRegionScale(0, 0.7138723001913112, 0.4573611686173884, 0.36527640941124423)


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
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 1.0964471457342215, -1.132521222038014, 0.09090821723483178)
        p.SetGlowRegionScale(0, 0.6151601417229323, 0.7190841289831522, 0.09225952137447825)
        p.SetGlowRegionOrientation(0, 0.0, 0.9996704442131799, 0.025671053087548964, 0.0, -0.025671053087548964, 0.9996704442131799)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -1.0964471457342215, -1.132521222038014, 0.09090821723483178)
        p.SetGlowRegionScale(0, 0.6151601417229323, 0.7190841289831522, 0.09225952137447825)
        p.SetGlowRegionOrientation(0, -0.0, 0.9996704442131799, 0.025671053087548964, 0.0, -0.025671053087548964, 0.9996704442131799)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.29, -1.834466518153527, 0.151)
        p.SetGlowRegionScale(0, 0.15752218869143766, 0.09923209328069126, 0.07909980689756281)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.29, -1.834466518153527, 0.151)
        p.SetGlowRegionScale(0, 0.15752218869143766, 0.09923209328069126, 0.07909980689756281)


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
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 0.0, 0.46911757430506484, -0.19423673529300256)
        p.SetLightEmitterRadius(0, 0.402018470686658)
        p.SetLightEmitterColor(0, 1.0, 0.9771261744784346, 0.8551137135161497)
        p.SetLightEmitterIntensity(0, 5.0)
        p.SetLightEmitterAxis(0, 3.4694469519536147e-16, 0.9930716673940593, -0.11751026942009399)
        p.SetLightEmitterLength(0, 1.4469840416461741)
        p.SetLightEmitterRadiusY(0, 0.6529530894378425)
        p.SetLightEmitterUp(0, 0.0, 0.11751026942009399, 0.9930716673940593)
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.88, -1.9739079526646612, 0.15)
        p.SetGlowRegionScale(0, 0.25, 1.7903034577123764, 0.25)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, -0.9246505700598948, -0.6522979993774463, 0.1759319908444521)
        p.SetLightEmitterRadius(0, 2.0378694561363577)
        p.SetLightEmitterColor(0, 1.0, 0.33882520219067114, 0.18068989733964003)
        p.SetLightEmitterIntensity(0, 0.75)
        p.SetLightEmitterAxis(0, 3.469446951953614e-16, 0.9749621446308409, 0.2223708985834959)
        p.SetLightEmitterLength(0, 2.0)
        p.SetLightEmitterRadiusY(0, 1.2710754670703601)
        p.SetLightEmitterUp(0, -0.0, -0.2223708985834959, 0.9749621446308409)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.88, -1.9739079526646612, 0.15)
        p.SetGlowRegionScale(0, 0.25, 1.7903034577123764, 0.25)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 0.9246505700598948, -0.6522979993774463, 0.1759319908444521)
        p.SetLightEmitterRadius(0, 2.0378694561363577)
        p.SetLightEmitterColor(0, 1.0, 0.33882520219067114, 0.18068989733964003)
        p.SetLightEmitterIntensity(0, 0.75)
        p.SetLightEmitterAxis(0, -3.469446951953614e-16, 0.9749621446308409, 0.2223708985834959)
        p.SetLightEmitterLength(0, 2.0)
        p.SetLightEmitterRadiusY(0, 1.2710754670703601)
        p.SetLightEmitterUp(0, 0.0, -0.2223708985834959, 0.9749621446308409)
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
        p.SetGlowRegionPosition(0, -1.9, -0.3330593280419536, -0.6)
        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.150005929372475, 1.150005929372475)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionPosition(0, 1.9, -0.3330593280419536, -0.6)
        p.SetGlowRegionAxis(0, -0.0, 1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.225)
        p.SetGlowRegionExtent(0, -1.150005929372475, 1.150005929372475)
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -0.8116406833827726, -0.5409088336822937, -0.05265865539521759)
        p.SetGlowRegionScale(0, 0.12364295502034257, 0.10482227838699068, 0.03141743612188066)
        p.SetGlowRegionOrientation(0, 0.0, 1.0, 0.0, -0.19280795802661935, 0.0, 0.9812365114087457)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.8116406833827726, -0.5409088336822937, -0.05265865539521759)
        p.SetGlowRegionScale(0, 0.12364295502034257, 0.10482227838699068, 0.03141743612188066)
        p.SetGlowRegionOrientation(0, -0.0, 1.0, 0.0, 0.19280795802661935, 0.0, 0.9812365114087457)
    p = find("Aft Torpedo")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 0.0, -0.5604198304861678, -0.037517662719546124)
        p.SetGlowRegionScale(0, 0.08011480331046698, 0.07592416385128685, 0.05345113721427131)


def _warbird(find):
    """warbird."""
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, -4.7, 0.6988002608127547, 0.066)
        p.SetGlowRegionScale(0, 0.29490591930461035, 1.5547297343574709, 0.35296719632815277)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, -4.909512239748867, 0.0, 0.0)
        p.SetLightEmitterRadius(0, 4.577067335277599)
        p.SetLightEmitterColor(0, 0.8106669198815697, 1.0, 0.3170241403016151)
        p.SetLightEmitterIntensity(0, 8.5)
        p.SetLightEmitterAxis(0, 0.9999359790389437, 5.689893001203927e-16, 0.011315379950721738)
        p.SetLightEmitterLength(0, 2.583640102500063)
        p.SetLightEmitterRadiusY(0, 2.468751373415951)
        p.SetLightEmitterUp(0, -0.011315379950721738, 0.0, 0.9999359790389437)
    p = find("Star Warp")
    if p is not None:
        p.SetGlowRegionShape(0, "Box")
        p.SetGlowRegionPosition(0, 4.7, 0.6988002608127547, 0.066)
        p.SetGlowRegionScale(0, 0.29490591930461035, 1.5547297343574709, 0.35296719632815277)
        p.SetLightEmitterKind(0, "cone")
        p.SetLightEmitterPosition(0, 4.909512239748867, 0.0, 0.0)
        p.SetLightEmitterRadius(0, 4.577067335277599)
        p.SetLightEmitterColor(0, 0.8106669198815697, 1.0, 0.3170241403016151)
        p.SetLightEmitterIntensity(0, 8.5)
        p.SetLightEmitterAxis(0, -0.9999359790389437, 5.689893001203927e-16, 0.011315379950721738)
        p.SetLightEmitterLength(0, 2.583640102500063)
        p.SetLightEmitterRadiusY(0, 2.468751373415951)
        p.SetLightEmitterUp(0, 0.011315379950721738, 0.0, 0.9999359790389437)
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
        p.SetLightEmitterPosition(0, -1.8120760848591873, -6.096608935851515, 2.0044448559243495)
        p.SetLightEmitterRadius(0, 1.568755434458936)
        p.SetLightEmitterColor(0, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(0, 12.0)
        p.SetLightEmitterAxis(0, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(0, 3.1730451523104186)
        p.SetLightEmitterRadiusY(0, 1.6224196667110584)
        p.SetLightEmitterUp(0, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(1, "cone")
        p.SetLightEmitterPosition(1, 1.8120760848591873, -6.096608935851515, 2.0044448559243495)
        p.SetLightEmitterRadius(1, 1.568755434458936)
        p.SetLightEmitterColor(1, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(1, 12.0)
        p.SetLightEmitterAxis(1, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(1, 3.1730451523104186)
        p.SetLightEmitterRadiusY(1, 1.6224196667110584)
        p.SetLightEmitterUp(1, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(2, "cone")
        p.SetLightEmitterPosition(2, 1.8120760848591873, -3.5630169523155217, 2.0044448559243495)
        p.SetLightEmitterRadius(2, 1.568755434458936)
        p.SetLightEmitterColor(2, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(2, 12.0)
        p.SetLightEmitterAxis(2, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(2, 3.1730451523104186)
        p.SetLightEmitterRadiusY(2, 1.6224196667110584)
        p.SetLightEmitterUp(2, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(3, "cone")
        p.SetLightEmitterPosition(3, -1.8120760848591873, -3.5630169523155217, 2.0044448559243495)
        p.SetLightEmitterRadius(3, 1.568755434458936)
        p.SetLightEmitterColor(3, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(3, 12.0)
        p.SetLightEmitterAxis(3, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(3, 3.1730451523104186)
        p.SetLightEmitterRadiusY(3, 1.6224196667110584)
        p.SetLightEmitterUp(3, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(4, "cone")
        p.SetLightEmitterPosition(4, -1.8120760848591873, -1.3884038026898926, 2.0044448559243495)
        p.SetLightEmitterRadius(4, 1.568755434458936)
        p.SetLightEmitterColor(4, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(4, 12.0)
        p.SetLightEmitterAxis(4, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(4, 3.1730451523104186)
        p.SetLightEmitterRadiusY(4, 1.6224196667110584)
        p.SetLightEmitterUp(4, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(5, "cone")
        p.SetLightEmitterPosition(5, 1.8120760848591873, -1.3884038026898926, 2.0044448559243495)
        p.SetLightEmitterRadius(5, 1.568755434458936)
        p.SetLightEmitterColor(5, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(5, 12.0)
        p.SetLightEmitterAxis(5, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(5, 3.1730451523104186)
        p.SetLightEmitterRadiusY(5, 1.6224196667110584)
        p.SetLightEmitterUp(5, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(6, "cone")
        p.SetLightEmitterPosition(6, -1.8120760848591873, 1.011182205997092, 2.0044448559243495)
        p.SetLightEmitterRadius(6, 1.568755434458936)
        p.SetLightEmitterColor(6, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(6, 12.0)
        p.SetLightEmitterAxis(6, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(6, 3.1730451523104186)
        p.SetLightEmitterRadiusY(6, 1.6224196667110584)
        p.SetLightEmitterUp(6, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(7, "cone")
        p.SetLightEmitterPosition(7, 1.8120760848591873, 1.011182205997092, 2.0044448559243495)
        p.SetLightEmitterRadius(7, 1.568755434458936)
        p.SetLightEmitterColor(7, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(7, 12.0)
        p.SetLightEmitterAxis(7, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(7, 3.1730451523104186)
        p.SetLightEmitterRadiusY(7, 1.6224196667110584)
        p.SetLightEmitterUp(7, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(8, "cone")
        p.SetLightEmitterPosition(8, 1.8120760848591873, 3.390414665193382, 2.0044448559243495)
        p.SetLightEmitterRadius(8, 1.568755434458936)
        p.SetLightEmitterColor(8, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(8, 12.0)
        p.SetLightEmitterAxis(8, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(8, 3.1730451523104186)
        p.SetLightEmitterRadiusY(8, 1.6224196667110584)
        p.SetLightEmitterUp(8, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(9, "cone")
        p.SetLightEmitterPosition(9, -1.8120760848591873, 3.390414665193382, 2.0044448559243495)
        p.SetLightEmitterRadius(9, 1.568755434458936)
        p.SetLightEmitterColor(9, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(9, 12.0)
        p.SetLightEmitterAxis(9, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(9, 3.1730451523104186)
        p.SetLightEmitterRadiusY(9, 1.6224196667110584)
        p.SetLightEmitterUp(9, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(10, "cone")
        p.SetLightEmitterPosition(10, -1.8120760848591873, 5.7887470328111945, 2.0044448559243495)
        p.SetLightEmitterRadius(10, 1.568755434458936)
        p.SetLightEmitterColor(10, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(10, 12.0)
        p.SetLightEmitterAxis(10, 0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(10, 3.1730451523104186)
        p.SetLightEmitterRadiusY(10, 1.6224196667110584)
        p.SetLightEmitterUp(10, 0.00010986504541041213, 0.99999725634521, -0.0023399213072288596)
        p.SetLightEmitterKind(11, "cone")
        p.SetLightEmitterPosition(11, 1.8120760848591873, 5.7887470328111945, 2.0044448559243495)
        p.SetLightEmitterRadius(11, 1.568755434458936)
        p.SetLightEmitterColor(11, 0.9967105263157895, 1.0, 0.993421052631579)
        p.SetLightEmitterIntensity(11, 12.0)
        p.SetLightEmitterAxis(11, -0.48866993000569015, -0.002095195796757821, -0.872466222648652)
        p.SetLightEmitterLength(11, 3.1730451523104186)
        p.SetLightEmitterRadiusY(11, 1.6224196667110584)
        p.SetLightEmitterUp(11, -0.00010986504541041235, 0.99999725634521, -0.0023399213072288596)


def _fedstarbase(find):
    """fedstarbase."""
    return


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
    "fedstarbase": _fedstarbase,
}
