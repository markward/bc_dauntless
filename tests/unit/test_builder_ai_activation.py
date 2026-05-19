"""Unit tests for BuilderAI activation — first-tick topological build."""
import sys
import types

import pytest

import App
from engine.appc.ai import BuilderAI_Create, PlainAI_Create, SequenceAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


def _make_module_with_builders(**funcs) -> str:
    """Register a synthetic module containing BuilderCreateN functions.
    Returns the module name so the caller can pass it to BuilderAI_Create."""
    name = f"_test_builder_{id(funcs)}"
    mod = types.ModuleType(name)
    for fn_name, fn in funcs.items():
        setattr(mod, fn_name, fn)
    sys.modules[name] = mod
    return name


def test_synthetic_3block_graph_builds_in_dep_order():
    """Block C depends on A and B. Activation builds A and B first,
    then C(pShip, a_result, b_result). C's result becomes _contained_ai."""
    order = []

    def BuilderCreate1(pShip):
        order.append("A")
        return PlainAI_Create(pShip, "A")

    def BuilderCreate2(pShip):
        order.append("B")
        return PlainAI_Create(pShip, "B")

    def BuilderCreate3(pShip, a_ai, b_ai):
        order.append("C")
        seq = SequenceAI_Create(pShip, "C")
        seq.AddAI(a_ai); seq.AddAI(b_ai)
        return seq

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1,
        BuilderCreate2=BuilderCreate2,
        BuilderCreate3=BuilderCreate3,
    )

    ship = ShipClass()
    builder = BuilderAI_Create(ship, "TestRoot", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddAIBlock("C", "BuilderCreate3")
    builder.AddDependency("C", "A")
    builder.AddDependency("C", "B")

    tick_ai(builder, game_time=0.01)

    assert order == ["A", "B", "C"] or order == ["B", "A", "C"]
    assert builder._activated is True
    assert builder._activation_failed is False
    assert builder._contained_ai is not None
    assert builder._contained_ai.GetName() == "C"


def test_activation_idempotent_no_rebuild_on_second_tick():
    """Once activated, subsequent ticks don't re-call builders."""
    calls = []

    def BuilderCreate1(pShip):
        calls.append(1)
        return PlainAI_Create(pShip, "A")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    tick_ai(builder, game_time=0.5)
    tick_ai(builder, game_time=1.0)

    assert calls == [1]


def test_dep_objects_passed_as_kwargs():
    """AddDependencyObject(block, attr, value) → kwarg attr=value at build."""
    captured = {}

    def BuilderCreate1(pShip, **kwargs):
        captured.update(kwargs)
        return PlainAI_Create(pShip, "A")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddDependencyObject("A", "sTarget", "player")
    builder.AddDependencyObject("A", "fDistance", 295.0)

    tick_ai(builder, game_time=0.01)
    assert captured == {"sTarget": "player", "fDistance": 295.0}


def test_dep_results_passed_in_declaration_order():
    """AddDependency calls in order (X→A) then (X→B) → builder receives
    (a_result, b_result) as positional args."""
    received = []

    def BuilderCreate1(pShip):
        return PlainAI_Create(pShip, "A")

    def BuilderCreate2(pShip):
        return PlainAI_Create(pShip, "B")

    def BuilderCreate3(pShip, *deps):
        received.extend(d.GetName() for d in deps)
        return PlainAI_Create(pShip, "C")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
        BuilderCreate3=BuilderCreate3,
    )

    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddAIBlock("C", "BuilderCreate3")
    builder.AddDependency("C", "A")
    builder.AddDependency("C", "B")

    tick_ai(builder, game_time=0.01)
    assert received == ["A", "B"]


def test_missing_builder_function_sets_activation_failed():
    mod_name = _make_module_with_builders()  # no functions
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True
    assert "BuilderCreate1" in builder._activation_error[1]


def test_cyclic_dependency_sets_activation_failed():
    """A depends on B; B depends on A. Topological sort can't resolve."""
    def BuilderCreate1(pShip, b): return PlainAI_Create(pShip, "A")
    def BuilderCreate2(pShip, a): return PlainAI_Create(pShip, "B")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
    )
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddDependency("A", "B")
    builder.AddDependency("B", "A")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True


def test_builder_raising_sets_activation_failed():
    def BuilderCreate1(pShip):
        raise RuntimeError("boom")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True
    assert "boom" in builder._activation_error[1]


def test_builder_returning_none_for_last_block_fails_activation():
    def BuilderCreate1(pShip):
        return None

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True


def test_intermediate_none_does_not_fail_activation():
    """A returns None mid-graph. Dependents of A get None as the dep arg
    (it's the builder function's job to handle that). The graph as a
    whole only fails if the LAST block returns None."""
    def BuilderCreate1(pShip):
        return None

    def BuilderCreate2(pShip, a):
        return PlainAI_Create(pShip, "B")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
    )
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddDependency("B", "A")

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True
    assert builder._activation_failed is False
    assert builder._contained_ai.GetName() == "B"


def test_failed_activation_short_circuits_subsequent_ticks():
    """After activation_failed, tick_ai must short-circuit without
    re-invoking the builder."""
    calls = []

    def BuilderCreate1(pShip):
        calls.append(1)
        raise RuntimeError("boom")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    tick_ai(builder, game_time=0.5)
    assert len(calls) == 1
