"""Tests for weapon_splash_radius — the R_hit resolver from spec §3.2."""

from engine.appc.combat import PHASER_DEFAULT_DAMAGE_RADIUS, weapon_splash_radius


class _FakeWeaponProperty:
    def __init__(self, drf):
        self._drf = drf

    def GetDamageRadiusFactor(self):
        return self._drf


class _FakePayloadTemplate:
    def __init__(self, drf):
        self._drf = drf

    def GetDamageRadiusFactor(self):
        return self._drf


def test_payload_drf_wins_over_the_tube_when_both_set():
    """Measured on stbc.exe (CombatTap DS r=): photon hits carry the
    torpedo's 0.13 (258 hits), never the Galaxy/Sovereign tubes' 0.20."""
    hp = _FakeWeaponProperty(0.20)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.13


def test_payload_drf_used_when_hardpoint_zero():
    hp = _FakeWeaponProperty(0.0)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.13


def test_payload_drf_used_when_hardpoint_none():
    payload = _FakePayloadTemplate(0.14)
    assert weapon_splash_radius(None, payload) == 0.14


def test_phaser_default_when_both_absent():
    assert weapon_splash_radius(None, None) == PHASER_DEFAULT_DAMAGE_RADIUS
    assert PHASER_DEFAULT_DAMAGE_RADIUS == 0.15


def test_phaser_default_when_both_zero():
    hp = _FakeWeaponProperty(0.0)
    payload = _FakePayloadTemplate(0.0)
    assert weapon_splash_radius(hp, payload) == PHASER_DEFAULT_DAMAGE_RADIUS


def test_akira_torp_uses_the_photon_value_not_the_tube():
    # Akira hardpoint DRF = 0.60, photon payload DRF = 0.13. The old
    # "hardpoint overrides" hypothesis gave 0.60; the original uses the
    # projectile's own value (Galaxy/Sovereign photons: 0.13 on every hit).
    hp = _FakeWeaponProperty(0.60)
    payload = _FakePayloadTemplate(0.13)
    assert weapon_splash_radius(hp, payload) == 0.13
