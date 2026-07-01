"""Tests for the BC Federation registry / hull-name texture-swap queue
(engine/appc/registry_texture.py + ObjectClass.ReplaceTexture)."""
import pytest

from engine.appc import registry_texture
from engine.appc.objects import ObjectClass


@pytest.fixture(autouse=True)
def _clean():
    registry_texture.reset()
    yield
    registry_texture.reset()


class _Ship:
    """Minimal ship: a script name (drives class-default lookup) and a real
    ReplaceTexture that routes into the queue exactly like ObjectClass does."""
    def __init__(self, script=""):
        self._script = script

    def GetScript(self):
        return self._script

    def ReplaceTexture(self, new_path, old_name):
        registry_texture.queue_replace(self, new_path, old_name)


# ── queue + retrieval ───────────────────────────────────────────────────────

def test_queue_replace_records_and_retrieves():
    ship = _Ship()
    registry_texture.queue_replace(
        ship, "Data/Models/SharedTextures/FedShips/Dauntless.tga", "ID")
    reps = registry_texture.replacements_for(ship)
    assert len(reps) == 1
    old, new_abs = reps[0]
    assert old == "ID"
    # Resolved to an absolute path ending in the requested file.
    assert new_abs.replace("\\", "/").lower().endswith("dauntless.tga")


def test_empty_ship_has_no_replacements():
    assert registry_texture.replacements_for(_Ship()) == []
    assert registry_texture.has_replacements(_Ship()) is False


def test_last_write_wins_per_old_name():
    ship = _Ship()
    registry_texture.queue_replace(ship, "a/Dauntless.tga", "ID")
    registry_texture.queue_replace(ship, "a/Venture.tga", "ID")
    reps = registry_texture.replacements_for(ship)
    assert len(reps) == 1
    assert reps[0][1].lower().endswith("venture.tga")


def test_distinct_old_names_coexist():
    ship = _Ship()
    registry_texture.queue_replace(ship, "a/Dauntless.tga", "ID")
    registry_texture.queue_replace(ship, "a/Panel.tga", "PANEL")
    olds = {old for old, _ in registry_texture.replacements_for(ship)}
    assert olds == {"ID", "PANEL"}


def test_ships_are_independent():
    a, b = _Ship(), _Ship()
    registry_texture.queue_replace(a, "x/Dauntless.tga", "ID")
    assert registry_texture.has_replacements(a)
    assert not registry_texture.has_replacements(b)


def test_clear_for_and_reset():
    a, b = _Ship(), _Ship()
    registry_texture.queue_replace(a, "x/Dauntless.tga", "ID")
    registry_texture.queue_replace(b, "x/Venture.tga", "ID")
    registry_texture.clear_for(a)
    assert not registry_texture.has_replacements(a)
    assert registry_texture.has_replacements(b)
    registry_texture.reset()
    assert not registry_texture.has_replacements(b)


# ── class-default map ───────────────────────────────────────────────────────

@pytest.mark.parametrize("cls,expect_leaf", [
    ("Galaxy", "dauntless.tga"),
    ("Sovereign", "sovereign.tga"),
    ("Nebula", "berkeley.tga"),
    ("Akira", "geronimo.tga"),
    ("Ambassador", "zhukov.tga"),
])
def test_apply_class_default_maps_federation_classes(cls, expect_leaf):
    ship = _Ship(script="ships." + cls)
    applied = registry_texture.apply_class_default(ship)
    assert applied is True
    reps = registry_texture.replacements_for(ship)
    assert len(reps) == 1
    old, new_abs = reps[0]
    assert old == registry_texture.REGISTRY_OLD_NAME == "ID"
    assert new_abs.replace("\\", "/").lower().endswith(expect_leaf)


def test_apply_class_default_ignores_non_federation():
    ship = _Ship(script="ships.Galor")
    assert registry_texture.apply_class_default(ship) is False
    assert registry_texture.replacements_for(ship) == []


def test_apply_class_default_handles_bare_class_name():
    # GetScript may return the leaf directly in some paths; still resolves.
    ship = _Ship(script="Galaxy")
    assert registry_texture.apply_class_default(ship) is True


def test_apply_class_default_no_script_is_noop():
    ship = _Ship(script="")
    assert registry_texture.apply_class_default(ship) is False


# ── real ObjectClass.ReplaceTexture routes into the queue ───────────────────

def test_objectclass_replace_texture_queues():
    ship = ObjectClass()
    ship.SetScript("ships.Galaxy")
    ship.ReplaceTexture(
        "Data/Models/SharedTextures/FedShips/Dauntless.tga", "ID")
    reps = registry_texture.replacements_for(ship)
    assert len(reps) == 1
    assert reps[0][0] == "ID"
    assert reps[0][1].lower().endswith("dauntless.tga")


def test_objectclass_apply_class_default_end_to_end():
    ship = ObjectClass()
    ship.SetScript("ships.Sovereign")
    assert registry_texture.apply_class_default(ship) is True
    reps = registry_texture.replacements_for(ship)
    assert reps and reps[0][1].lower().endswith("sovereign.tga")
