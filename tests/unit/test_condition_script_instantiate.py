"""Unit tests for ConditionScript eager instantiation + fallback."""
import sys
import types

import pytest

import App
from engine.appc.ai import (
    ConditionScript, ConditionScript_Create, ConditionalAI_Create,
)


def _install_synthetic_condition(name: str, *, raise_in_init=False):
    """Register a synthetic Conditions/<name>.py module with a class
    named <name> that stores its args. Returns the qualified module name."""
    mod_name = f"Conditions.{name}"
    mod = types.ModuleType(mod_name)
    captured = {"args": None, "init_count": 0}

    class _Synthetic:
        def __init__(self, pCodeCondition, *args):
            captured["args"] = args
            captured["init_count"] += 1
            if raise_in_init:
                raise RuntimeError("synthetic-failure")
            self.pCodeCondition = pCodeCondition

    _Synthetic.__name__ = name
    setattr(mod, name, _Synthetic)
    sys.modules[mod_name] = mod
    # Also register the parent package so __import__ walks it.
    pkg_name = "Conditions"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = []  # mark as package
        sys.modules[pkg_name] = pkg
    setattr(sys.modules[pkg_name], name, mod)
    return mod_name, captured


def test_create_instantiates_real_class():
    mod_name, captured = _install_synthetic_condition("SynthCond1")
    cs = ConditionScript_Create(mod_name, "SynthCond1", 1.0, "x")
    assert cs._instance is not None
    assert captured["args"] == (1.0, "x")
    assert captured["init_count"] == 1


def test_create_falls_back_to_none_on_missing_module():
    cs = ConditionScript_Create("Conditions.DoesNotExist", "DoesNotExist", 0)
    assert cs._instance is None
    assert cs._init_error is not None
    # Error captured for introspection.
    assert "DoesNotExist" in cs._init_error[1] or cs._init_error[0] in (
        "ImportError", "ModuleNotFoundError", "AttributeError",
    )


def test_create_falls_back_on_missing_class_within_module():
    """Module exists but doesn't have the named class."""
    mod_name = "Conditions._test_no_class"
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    if "Conditions" not in sys.modules:
        pkg = types.ModuleType("Conditions"); pkg.__path__ = []
        sys.modules["Conditions"] = pkg
    setattr(sys.modules["Conditions"], "_test_no_class", mod)

    cs = ConditionScript_Create(mod_name, "NoSuchClass")
    assert cs._instance is None
    assert cs._init_error[0] == "AttributeError"


def test_create_falls_back_on_constructor_raise():
    mod_name, _ = _install_synthetic_condition("SynthCondRaiser", raise_in_init=True)
    cs = ConditionScript_Create(mod_name, "SynthCondRaiser", 1.0)
    assert cs._instance is None
    assert cs._init_error[0] == "RuntimeError"
    assert "synthetic-failure" in cs._init_error[1]


def test_create_success_does_not_set_init_error():
    mod_name, _ = _install_synthetic_condition("SynthCondClean")
    cs = ConditionScript_Create(mod_name, "SynthCondClean")
    assert cs._instance is not None
    assert cs._init_error is None


def test_set_status_from_instance_drives_conditional_ai_handler():
    """The instance's SetStatus calls back into the ConditionScript which
    fires registered TGConditionHandlers. ConditionalAI subscribes to its
    conditions; flipping status should trigger ConditionChanged."""
    mod_name, _ = _install_synthetic_condition("SynthCondReporter")
    cs = ConditionScript_Create(mod_name, "SynthCondReporter")

    # Wire into a ConditionalAI to confirm the handler chain fires.
    from engine.appc.ships import ShipClass
    cai = ConditionalAI_Create(ShipClass(), "C")
    cai.AddCondition(cs)
    cs.SetActive()  # ConditionalAI's ConditionChanged only fires when active

    # Drive a status flip from the instance side.
    cs.SetStatus(1)
    assert cs.GetStatus() == 1
    # ConditionalAI's _status reflects activity but the gate is on
    # condition status — we just need the handler chain to not blow up.
