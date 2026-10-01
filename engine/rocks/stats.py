"""Hull and mass for rocks that have no hardpoint file (rock-class spec §1).

Calibrated on stock BC `Asteroid` (hardpoints/asteroid.py): radius 0.8 GU,
MaxCondition 2500, mass 400. Hull scales with surface (r^2), mass with volume
(r^3). A broken-off piece inherits from its parent instead, so a mission's
authored HP (E1M2 sets it per moving rock) carries down to the pieces.
"""
REF_RADIUS_GU = 0.8
REF_HULL = 2500.0
REF_MASS = 400.0


def size_hull(r_gu: float) -> float:
    return REF_HULL * (float(r_gu) / REF_RADIUS_GU) ** 2


def size_mass(r_gu: float) -> float:
    return REF_MASS * (float(r_gu) / REF_RADIUS_GU) ** 3


def piece_hull(parent_max: float, v_ratio: float) -> float:
    return float(parent_max) * float(v_ratio) ** (2.0 / 3.0)


def piece_mass(parent_mass: float, v_ratio: float) -> float:
    return float(parent_mass) * float(v_ratio)


def quantise_radius(r_gu: float) -> float:
    """`r_gu` to 2 significant figures (1.2345 -> 1.2, 0.0876 -> 0.088).
    Model loads and damage-volume caches key on "#s=<scale>", so continuous
    radii would cost a fresh model load and first-hit field bake per rock."""
    return float(f"{float(r_gu):.2g}")
