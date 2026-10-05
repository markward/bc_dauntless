"""engine.appc.science_scan_labels._display_name_as: the save/restore
context manager behind the Scan Object unknown-name wrap.

Must be save/restore, not a blind `del`: a caller may already have its own
instance-level GetDisplayName override in place on the object, and the
context can be entered reentrantly on the SAME object (CreateScanButton and
ExitedSet can both run against the same contact during one event dispatch).
An unconditional delete would permanently destroy a pre-existing override, or
-- in the nested case -- have the inner call's cleanup delete the attribute
the outer call still relies on.
"""
from engine.appc.objects import ObjectClass
from engine.appc.science_scan_labels import _display_name_as


def _obj(name="Real"):
    obj = ObjectClass()
    obj.SetName(name)
    return obj


def test_restores_to_the_class_method_when_there_was_no_prior_override():
    obj = _obj()
    with _display_name_as(obj, "Unknown 1"):
        assert obj.GetDisplayName() == "Unknown 1"
    assert obj.GetDisplayName() == "Real"
    # Restored by DELETING the instance attr, not by leaving an empty one --
    # GetDisplayName falls back to the class method again.
    assert "GetDisplayName" not in obj.__dict__


def test_a_pre_existing_instance_override_survives_the_context():
    obj = _obj()
    obj.GetDisplayName = lambda: "Custom Override"
    with _display_name_as(obj, "Unknown 1"):
        assert obj.GetDisplayName() == "Unknown 1"
    assert obj.GetDisplayName() == "Custom Override"


def test_nested_use_on_the_same_object_restores_correctly():
    obj = _obj()
    with _display_name_as(obj, "Outer"):
        assert obj.GetDisplayName() == "Outer"
        with _display_name_as(obj, "Inner"):
            assert obj.GetDisplayName() == "Inner"
        # The inner call's cleanup must restore the OUTER override, not
        # delete past it.
        assert obj.GetDisplayName() == "Outer"
    assert obj.GetDisplayName() == "Real"
    assert "GetDisplayName" not in obj.__dict__


def test_exception_inside_the_context_still_restores():
    obj = _obj()
    try:
        with _display_name_as(obj, "Unknown 1"):
            assert obj.GetDisplayName() == "Unknown 1"
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert obj.GetDisplayName() == "Real"
    assert "GetDisplayName" not in obj.__dict__


def test_exception_inside_the_context_restores_a_pre_existing_override():
    obj = _obj()
    obj.GetDisplayName = lambda: "Custom Override"
    try:
        with _display_name_as(obj, "Unknown 1"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert obj.GetDisplayName() == "Custom Override"
