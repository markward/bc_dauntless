"""App.SetClass_MakeDisplayName — readable label for a set/region name."""
import App
from engine.appc.sets import SetClass_MakeDisplayName


def test_trailing_digits_get_a_space():
    assert SetClass_MakeDisplayName("Vesuvi4") == "Vesuvi 4"
    assert SetClass_MakeDisplayName("Starbase12") == "Starbase 12"


def test_no_digits_unchanged():
    assert SetClass_MakeDisplayName("Albirea") == "Albirea"


def test_always_returns_str():
    assert isinstance(SetClass_MakeDisplayName(12345), str)


def test_exposed_on_App_as_real_callable():
    # Not a _NamedStub fallthrough.
    out = App.SetClass_MakeDisplayName("Vesuvi6")
    assert out == "Vesuvi 6"
    assert isinstance(out, str)
