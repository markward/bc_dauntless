import App
from engine.appc.ai import PlainAI, PlainAI_Create
from engine.appc.ships import ShipClass


def test_set_script_module_loads_real_class():
    """SetScriptModule('Stay') imports AI.PlainAI.Stay and instantiates Stay."""
    ship = ShipClass()
    pai = PlainAI_Create(ship, "TestStay")
    pai.SetScriptModule("Stay")
    inst = pai.GetScriptInstance()

    # Must be the real Stay class, not the _AIScriptInstance proxy.
    from AI.PlainAI import Stay as StayModule
    assert isinstance(inst, StayModule.Stay)


def test_script_instance_p_code_ai_points_back():
    """The loaded script's pCodeAI must point to the owning PlainAI."""
    ship = ShipClass()
    pai = PlainAI_Create(ship, "X")
    pai.SetScriptModule("Stay")
    assert pai.GetScriptInstance().pCodeAI is pai


def test_register_external_function_records_mapping():
    """BaseAI.SetExternalFunctions calls pCodeAI.RegisterExternalFunction(name, dict).
    The PlainAI must store the mapping so introspection works."""
    pai = PlainAI_Create(ShipClass(), "X")
    pai.RegisterExternalFunction("SetTarget", {"Name": "MySetTarget"})
    pai.RegisterExternalFunction("Foo", {"CodeID": 42, "FunctionName": "Bar"})
    funcs = pai.GetExternalFunctions()
    assert funcs["SetTarget"] == {"Name": "MySetTarget"}
    assert funcs["Foo"] == {"CodeID": 42, "FunctionName": "Bar"}


def test_stay_get_next_update_time_is_five_seconds():
    """Stay.GetNextUpdateTime returns 5.0 — sanity that the real module loads."""
    pai = PlainAI_Create(ShipClass(), "X")
    pai.SetScriptModule("Stay")
    assert pai.GetScriptInstance().GetNextUpdateTime() == 5.0


def test_set_script_module_replaces_instance():
    """Re-calling SetScriptModule swaps the script instance."""
    pai = PlainAI_Create(ShipClass(), "X")
    pai.SetScriptModule("Stay")
    first = pai.GetScriptInstance()
    pai.SetScriptModule("Stay")
    second = pai.GetScriptInstance()
    assert first is not second
