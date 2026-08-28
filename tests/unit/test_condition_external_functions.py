"""SDK conditions must receive their registered external-function callbacks.

THE GAP THIS PINS. Nine shipped Condition scripts define
``RegisterExternalFunctions(pAI)``; it is how a condition learns things it
cannot observe for itself. Two names are broadcast at it:

    SetTarget        -- AI/Preprocessors.py:1407 (SelectTarget), :2377,
                        AI/Compound/ChainFollowThroughWarp.py:146
    UsingWeaponType  -- AI/Preprocessors.py:290 (FireScript)

``RegisterExternalFunctions`` is never called from SDK script code (grep: the
only hit outside the nine ``def``s is a commented-out debug line), so the
engine is what calls it -- at the point a condition is attached to an AI.
Nothing in engine/ ever did, and ``ConditionalAI`` inherited the base no-op
``CallExternalFunction``, so both halves were dead: nothing registered, and a
registration would not have been dispatched anyway.

Live cost: ``ConditionUsingWeapon`` is set *entirely* by its callback (its
``__init__`` does ``SetStatus(0)`` and nothing else ever writes it), so every
gate that reads it -- NonFedAttack's ``FwdTorpsOrPulseReady`` and
``RearTorpsReadySortaClose...``, FedAttack's equivalents -- was permanently
false and the whole torpedo doctrine below it was unreachable.

Note the registration payload is a THIRD shape. ``BaseAI.SetExternalFunctions``
sends ``{"Name": method}`` and ``FireScript.CodeAISet`` sends the same;
conditions send ``{"CodeID": <condition objid>, "FunctionName": <name>}``, so
dispatch has to resolve the id back to the ConditionScript and call the method
on its *script instance*, not on the AI's own.
"""
import sys
import types

import pytest

import App
from engine.appc.ai import (
    ConditionScript,
    ConditionScript_Create,
    ConditionScript_GetByID,
    ConditionalAI_Create,
    PlainAI_Create,
    PreprocessingAI_Create,
)
from engine.appc.ships import ShipClass


def _install_condition(name: str, body: type):
    """Register a synthetic ``Conditions/<name>.py`` exposing class ``name``."""
    mod_name = f"Conditions.{name}"
    mod = types.ModuleType(mod_name)
    body.__name__ = name
    setattr(mod, name, body)
    sys.modules[mod_name] = mod
    pkg = sys.modules.get("Conditions")
    if pkg is None:
        pkg = types.ModuleType("Conditions")
        pkg.__path__ = []
        sys.modules["Conditions"] = pkg
    setattr(pkg, name, mod)
    return mod_name


class _Recorder:
    """Stand-in for a real Condition script: registers a hook, records calls."""

    external_name = "SetTarget"
    method_name = "SetTarget"

    def __init__(self, pCodeCondition, *args):
        self.pCodeCondition = pCodeCondition
        self.calls = []

    def RegisterExternalFunctions(self, pAI):
        pAI.RegisterExternalFunction(
            self.external_name,
            {"CodeID": self.pCodeCondition.GetObjID(),
             "FunctionName": self.method_name},
        )

    def SetTarget(self, sTarget):
        self.calls.append(sTarget)


def test_condition_script_has_a_resolvable_object_id():
    """``RegisterExternalFunctions`` calls ``self.pCodeCondition.GetObjID()``.

    In BC that is real published surface -- ``TGCondition`` derives from
    ``TGObject`` (sdk/.../App.py:2529) and ``TGObject.GetObjID`` is bound at
    App.py:371. Ours had no GetObjID at all, so the very first line of every
    condition's registration would have raised AttributeError.
    """
    a = ConditionScript_Create("", "")
    b = ConditionScript_Create("", "")
    assert a.GetObjID() != b.GetObjID()
    assert ConditionScript_GetByID(a.GetObjID()) is a
    assert ConditionScript_GetByID(b.GetObjID()) is b
    assert ConditionScript_GetByID(-1) is None


def test_add_condition_registers_the_conditions_external_functions():
    """Attaching a condition to a ConditionalAI is what wires its hooks."""
    _install_condition("RecorderA", type("RecorderA", (_Recorder,), {}))
    cond = ConditionScript_Create("Conditions.RecorderA", "RecorderA")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)

    assert "SetTarget" in node.GetExternalFunctions()


def test_call_external_function_reaches_the_condition_script_instance():
    """A ``CodeID`` mapping must resolve to the condition's script instance.

    This is the assertion a structural "was RegisterExternalFunctions called?"
    test would pass over: registration that resolves to nothing is exactly the
    bug.
    """
    _install_condition("RecorderB", type("RecorderB", (_Recorder,), {}))
    cond = ConditionScript_Create("Conditions.RecorderB", "RecorderB")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)

    node.CallExternalFunction("SetTarget", "Enemy-1")

    assert cond._instance.calls == ["Enemy-1"]


def test_two_conditions_registering_the_same_name_are_both_called():
    """A name->single-mapping registry silently drops one of them.

    Not hypothetical: 11 ConditionalAIs in the shipped SDK attach two or more
    conditions that all register ``SetTarget`` -- e.g.
    ``AI/Compound/FollowThroughWarp.py`` builds ``pTargetExistsInWrongSet``
    from a ConditionAnyInSameSet *and* a ConditionExists, and
    ``E6M4_AI_Galor2.py``'s ``pPlayerNotInRange`` from a ConditionAnyInSameSet
    *and* a ConditionInRange. Both halves have to learn the new target or the
    gate evaluates on a stale one.
    """
    _install_condition("RecorderC", type("RecorderC", (_Recorder,), {}))
    first = ConditionScript_Create("Conditions.RecorderC", "RecorderC")
    second = ConditionScript_Create("Conditions.RecorderC", "RecorderC")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(first)
    node.AddCondition(second)

    node.CallExternalFunction("SetTarget", "Enemy-2")

    assert first._instance.calls == ["Enemy-2"]
    assert second._instance.calls == ["Enemy-2"]


def test_distinct_names_on_one_node_dispatch_independently():
    """NonFedAttack's FwdTorpsOrPulseReady mixes both broadcast names."""
    _install_condition(
        "RecorderD",
        type("RecorderD", (_Recorder,),
             {"external_name": "UsingWeaponType", "method_name": "SetTarget"}),
    )
    _install_condition("RecorderE", type("RecorderE", (_Recorder,), {}))
    weapons = ConditionScript_Create("Conditions.RecorderD", "RecorderD")
    target = ConditionScript_Create("Conditions.RecorderE", "RecorderE")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(weapons)
    node.AddCondition(target)

    node.CallExternalFunction("UsingWeaponType", ["torp"])

    assert weapons._instance.calls == [["torp"]]
    assert target._instance.calls == []


def test_condition_without_register_external_functions_is_left_alone():
    """Most conditions (ConditionTorpsReady, ConditionFlagSet, ...) define no
    hook at all. Attaching one must not raise, and must register nothing."""

    class Plain:
        def __init__(self, pCodeCondition, *args):
            self.pCodeCondition = pCodeCondition

    _install_condition("RecorderF", Plain)
    cond = ConditionScript_Create("Conditions.RecorderF", "RecorderF")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)

    assert node.GetExternalFunctions() == {}
    node.CallExternalFunction("SetTarget", "Enemy-1")  # tolerant no-op


def test_a_raising_register_external_functions_does_not_break_wiring():
    """Condition construction is already tolerant of a broken script; the
    registration call has to be too, or one bad condition kills the AI tree."""

    class Angry(_Recorder):
        def RegisterExternalFunctions(self, pAI):
            raise RuntimeError("boom")

    _install_condition("RecorderG", Angry)
    cond = ConditionScript_Create("Conditions.RecorderG", "RecorderG")
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)  # must not raise

    assert node.GetConditions() == [cond]


# ── regression guards on the two pre-existing dispatch shapes ───────────────

def test_plain_ai_name_mapping_still_dispatches():
    """``BaseAI.SetExternalFunctions`` -> ``{"Name": <method>}`` on a PlainAI."""
    pai = PlainAI_Create(ShipClass(), "X")
    seen = []
    pai.GetScriptInstance().MySetTarget = seen.append
    pai.RegisterExternalFunction("SetTarget", {"Name": "MySetTarget"})

    pai.CallExternalFunction("SetTarget", "Enemy-1")

    assert seen == ["Enemy-1"]


def test_preprocessing_ai_function_name_mapping_still_dispatches():
    """``FireScript.CodeAISet`` registers on its wrapping PreprocessingAI."""
    node = PreprocessingAI_Create(ShipClass(), "Fire")
    seen = []

    class Inst:
        def SetTarget(self, s):
            seen.append(s)

    node._preprocessing_instance = Inst()
    node.RegisterExternalFunction("SetTarget", {"FunctionName": "SetTarget"})

    node.CallExternalFunction("SetTarget", "Enemy-1")

    assert seen == ["Enemy-1"]


def test_registering_the_same_mapping_twice_does_not_double_dispatch():
    """``CodeAISet`` can run again when a script module is re-set. One
    registration per (target, method) or the callback fires twice per broadcast."""
    pai = PlainAI_Create(ShipClass(), "X")
    seen = []
    pai.GetScriptInstance().MySetTarget = seen.append
    pai.RegisterExternalFunction("SetTarget", {"Name": "MySetTarget"})
    pai.RegisterExternalFunction("SetTarget", {"Name": "MySetTarget"})

    pai.CallExternalFunction("SetTarget", "Enemy-1")

    assert seen == ["Enemy-1"]


# ── the real shipped Condition classes ──────────────────────────────────────

# (class name, constructor args after pCodeCondition, the external name it must
# register). ConditionWarpingToMission is NOT found by grepping
# `Conditions/*.py` for a `RegisterExternalFunctions` def -- it defines none and
# INHERITS ConditionWarpingToSet's, so the real number of registrants is ten,
# not the nine that grep reports. It is the only such subclass in the tree.
_REAL_CONDITIONS = [
    ("ConditionInRange", (100.0, "Enemy-1", "Friend-1"), "SetTarget"),
    ("ConditionFacingToward",
     ("Friend-1", "Enemy-1", 30.0, App.TGPoint3_GetModelForward()), "SetTarget"),
    ("ConditionInPhaserFiringArc", ("Enemy-1", "Friend-1", 0), "SetTarget"),
    ("ConditionInSet", ("Enemy-1", "bridge", 1), "SetTarget"),
    ("ConditionAnyInSameSet", ("Friend-1", "Enemy-1"), "SetTarget"),
    ("ConditionExists", ("Enemy-1",), "SetTarget"),
    ("ConditionIncomingTorps", ("Friend-1", "Enemy-1"), "SetTarget"),
    ("ConditionWarpingToSet", ("Enemy-1", None), "SetTarget"),
    ("ConditionWarpingToMission", ("Enemy-1",), "SetTarget"),
    ("ConditionUsingWeapon", (App.CT_TORPEDO_SYSTEM,), "UsingWeaponType"),
]


@pytest.mark.parametrize("class_name,args,external_name", _REAL_CONDITIONS,
                         ids=[c[0] for c in _REAL_CONDITIONS])
def test_every_shipped_registrant_registers_when_bound(class_name, args,
                                                       external_name):
    """Two of these (ConditionFacingToward, ConditionInPhaserFiringArc) appear
    in no AI the integration test builds, so this is the only coverage they
    get."""
    cond = ConditionScript_Create(f"Conditions.{class_name}", class_name, *args)
    # ConditionScript swallows a construction failure and leaves _instance
    # None; without this the assertions below would pass over a condition that
    # never built rather than failing.
    assert cond._instance is not None, cond._init_error

    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)

    funcs = node.GetExternalFunctions()
    assert external_name in funcs, funcs
    assert funcs[external_name][0]["CodeID"] == cond.GetObjID()


def test_condition_in_set_registers_nothing_unless_it_was_told_to():
    """ConditionInSet's RegisterExternalFunctions is conditional on its
    bAllowSetTargetChanges flag (default 0). Proves the parametrized case above
    measures the registration and not merely "attaching anything registers"."""
    cond = ConditionScript_Create("Conditions.ConditionInSet", "ConditionInSet",
                                  "Enemy-1", "bridge")   # flag defaults to 0
    assert cond._instance is not None, cond._init_error
    node = ConditionalAI_Create(ShipClass(), "Gate")
    node.AddCondition(cond)

    assert node.GetExternalFunctions() == {}
