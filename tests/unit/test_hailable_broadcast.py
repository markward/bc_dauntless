"""ObjectClass.SetHailable broadcasts ET_HAILABLE_CHANGE.

Regression: the engine's SetHailable was a flag-only setter (planet.py) / a
silent __getattr__ stub (ships), so a target made hailable at runtime — the
E1M2 Haven colony, set hailable only after the asteroids are cleared — never
fired the ET_HAILABLE_CHANGE the SDK's Bridge/HelmMenuHandlers.HailableChange
listens for, so no Hail button was ever built and clicking "Hail" did nothing.
"""
import App
from engine.appc.objects import ObjectClass
from engine.appc.planet import Planet_Create

# Module-level captor: the broadcast dispatcher resolves handlers by qualified
# name (module.func), so the handler must live at module scope.
_received: list = []


def _on_hailable_change(dest, event):
    _received.append((event.GetSource(), event.GetBool()))


def _subscribe():
    _received.clear()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_HAILABLE_CHANGE, None, __name__ + "._on_hailable_change")


def test_set_hailable_true_broadcasts_change():
    _subscribe()
    obj = ObjectClass()
    obj.SetName("Haven")
    obj.SetHailable(1)
    assert len(_received) == 1
    src, val = _received[0]
    assert src is obj
    assert val == 1


def test_is_hailable_reflects_state():
    obj = ObjectClass()
    assert obj.IsHailable() == 0
    obj.SetHailable(1)
    assert obj.IsHailable() == 1
    obj.SetHailable(0)
    assert obj.IsHailable() == 0


def test_no_broadcast_when_state_unchanged():
    _subscribe()
    obj = ObjectClass()
    obj.SetHailable(0)      # already False -> no event
    assert _received == []
    obj.SetHailable(1)
    obj.SetHailable(1)      # already True -> no second event
    assert len(_received) == 1


def test_set_hailable_false_broadcasts_bool_zero():
    obj = ObjectClass()
    obj.SetHailable(1)
    _subscribe()            # subscribe after the True so we only capture the False
    obj.SetHailable(0)
    assert len(_received) == 1
    assert _received[0][1] == 0


def test_set_display_name_does_not_change_internal_name():
    """Display name and internal name are separate fields. SetDisplayName must
    never touch GetName() — internal names key set membership, friendly/enemy
    grouping, target selection and mission GetName() checks. GetDisplayName
    falls back to the internal name until a display name is set."""
    obj = ObjectClass()
    obj.SetName("Facility")
    assert obj.GetDisplayName() == "Facility"     # fallback to internal name
    obj.SetDisplayName("Haven Facility")
    assert obj.GetDisplayName() == "Haven Facility"
    assert obj.GetName() == "Facility"            # internal name unchanged


def test_hailable_defaults_match_native_appc():
    """Native-Appc defaults: SHIPS default hailable (missions SetHailable(FALSE)
    to hide debris/hulks/probes; E1M2's Facility is hailable with no explicit
    call), while planets/suns/bare objects default NOT hailable (Haven opts in
    via SetHailable(TRUE)). A broken __init__ chain leaving _hailable as a
    truthy __getattr__ stub would make bare ObjectClass wrongly report hailable."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.planet import Planet_Create, Sun_Create
    assert ShipClass_Create("Galaxy").IsHailable() == 1     # ships default hailable
    assert Planet_Create(100.0, "x.nif").IsHailable() == 0  # planets do not
    assert Sun_Create(800.0, 200.0, 100.0).IsHailable() == 0
    assert ObjectClass().IsHailable() == 0                  # bare objects do not


def test_planet_inherits_hailable_broadcast():
    _subscribe()
    p = Planet_Create(200.0, "iceplanet.nif")
    p.SetName("Haven")
    assert p.IsHailable() == 0
    p.SetHailable(1)
    assert len(_received) == 1
    assert _received[0][0] is p
    assert p.IsHailable() == 1
