"""The tree-walk differential harness proves itself (phase 6 AI part 4, Task 1).

The native side runs the native roster (Task 2), the native condition
evaluation (Task 3) and the native walk (Task 4). What
these tests pin, besides the two sides agreeing, is that the harness is
deterministic (two Python runs agree call for call and field for field), that
each scene reaches the driver paths it claims (asserted on the recorded call
log, not on the scene's intent), and that it fails when the sides differ.
"""
import gc
import sys
import types
from collections import Counter

import pytest

import App

from tests.helpers import ai_walk_diff as awd
from tests.helpers import ai_walker_oracle as oracle

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

needs_native = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")


def _k1_scene(dumb_fire=False, wrap_status=True, wrap_activation=True):
    def build(mp):
        from engine import host_loop
        from engine.appc import sensor_contacts
        from engine.appc.ship_iter import iter_ships
        from engine.core.loop import TICK_DELTA
        from tests.helpers import k1_fight as k1d
        import App
        if dumb_fire:
            from engine.dev_missions import combat_stress
            mp.setattr(combat_stress, "_AI_DIFFICULTY", 0.0)
        gc.collect()
        scene, loop = k1d._loop_setup(mp, k1d.ON)

        def step(i):
            loop.tick()
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=scene.player,
                                          push_render_data=False)
            host_loop._combat_tick_boundary()
            sensor_contacts.tick(scene.player,
                                 App.g_kUtopiaModule.GetGameTime())
        return awd.Scene(lambda: list(iter_ships()), step, wrap_roster=False,
                         wrap_condition_status=wrap_status,
                         wrap_node_activation=wrap_activation)
    return build



# ── synthetic trees ──────────────────────────────────────────────────────────

US_ACTIVE = 0
US_DONE = 1
US_DORMANT = 2


def _ai():
    from engine.appc import ai
    return ai


def _driver():
    from engine.appc import ai_driver
    return ai_driver


class Leaf:
    """A PlainAI script. ``done_after`` Updates it reports US_DONE;
    ``dormant`` makes it report US_DORMANT; ``on_update(n)`` is a hook."""

    def __init__(self, ai, interval=0.0, done_after=None, dormant=False,
                 on_update=None):
        self.pCodeAI = ai
        self.interval = interval
        self.done_after = done_after
        self.dormant = dormant
        self.on_update = on_update
        self.n = 0

    def Update(self):
        self.n += 1
        if self.on_update is not None:
            self.on_update(self.n)
        if self.dormant:
            return US_DORMANT
        if self.done_after is not None and self.n >= self.done_after:
            return US_DONE
        return US_ACTIVE

    def GetNextUpdateTime(self):
        return self.interval

    def Reset(self):
        self.n = 0


class Pre:
    """A preprocessor instance: ``PreUpdate(dt)`` (arity 1, like the SDK's)."""

    def __init__(self, ai, interval=0.0, on_update=None, result=0):
        self.pCodeAI = ai
        self.interval = interval
        self.on_update = on_update
        self.result = result
        self.n = 0

    def PreUpdate(self, dEndTime):
        self.n += 1
        if self.on_update is not None:
            self.on_update(self.n)
        return self.result

    def GetNextUpdateTime(self):
        return self.interval


def _ship(name="S"):
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.SetName(name)
    return ship


def _leaf(ship, name, **kw):
    node = _ai().PlainAI_Create(ship, name)
    node._script_instance = Leaf(node, **kw)
    return node


def _pre(ship, name, contained=None, **kw):
    node = _ai().PreprocessingAI_Create(ship, name)
    node._preprocessing_instance = Pre(node, **kw)
    node._preprocessing_method = "PreUpdate"
    if contained is not None:
        node.SetContainedAI(contained)
    return node


def _plist(ship, name, *children):
    node = _ai().PriorityListAI_Create(ship, name)
    for prio, child in children:
        node.AddAI(child, prio)
    return node


def _install(ship, root):
    ship.SetAI(root)
    return root


def _cond(status=0):
    cond = _ai().TGCondition()
    cond.SetStatus(status)
    return cond


def _conditional(ship, name, cond, contained):
    node = _ai().ConditionalAI_Create(ship, name)

    def EvalFunc(bOn):
        return US_ACTIVE if bOn else US_DORMANT
    node.AddCondition(cond)
    node.SetEvaluationFunction(EvalFunc)
    node.SetContainedAI(contained)
    return node


def _scene_of(mp, ships, actions=None, **kw):
    """A synthetic scene: `actions[i]()` runs before tick i's walk."""
    actions = actions or {}

    def step(i):
        if i in actions:
            actions[i]()
        _driver().tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, ships, step, **kw)


def _count(rec, name):
    return rec.calls()[name]


def _states(rec, field, node_name=None):
    """Every value `field` took across the run, by tick, for ships' nodes."""
    out = []
    for _log, snap in rec.ticks:
        for ship in snap["ships"].values():
            for st in ship["nodes"].values():
                out.append(st[field])
    return out


# ── RandomAI (NoSensorsEvasive's shape) ──────────────────────────────────────

def _random_evasive(mp):
    ship = _ship()
    leaves = [_leaf(ship, "Drift%d" % i, done_after=3, interval=0.05)
              for i in range(4)]
    rnd = _ai().RandomAI_Create(ship, "Random")
    for lf in leaves:
        rnd.AddAI(lf)
    loop = _ai().SequenceAI_Create(ship, "LoopForever")
    loop.SetLoopCount(-1)
    loop.SetSkipDormant(0)
    loop.AddAI(rnd)
    cond = _cond(0)
    gated = _conditional(ship, "SensorsDisabled", cond, loop)
    root = _plist(ship, "Root", (1, gated),
                  (2, _leaf(ship, "Idle", interval=0.1)))
    _install(ship, root)
    return _scene_of(mp, [ship], {2: lambda: cond.SetStatus(1),
                                  120: lambda: cond.SetStatus(0),
                                  170: lambda: cond.SetStatus(1)})


def test_random_ai_tree_no_sensors_evasive_shape():
    rec = awd.run_walk_diff(_random_evasive, 300)
    assert _count(rec, "random.choice") >= 6, rec.calls()
    assert _count(rec, "eval") > 0
    assert _count(rec, "cond.SetActive") >= 2        # re-gated by the toggle
    assert _count(rec, "cond.SetInactive") >= 1


# ── SequenceAI: skip_dormant 0 / 1, finite and endless loops ─────────────────

def _sequence(skip_dormant, loops):
    def build(mp):
        ship = _ship()
        cond = _cond(0)
        first = _leaf(ship, "A", done_after=2, interval=0.03)
        held = _conditional(ship, "Held", cond,
                            _leaf(ship, "BInner", done_after=2))
        last = _leaf(ship, "C", done_after=2, interval=0.03)
        seq = _ai().SequenceAI_Create(ship, "Seq")
        seq.SetLoopCount(loops)
        seq.SetSkipDormant(skip_dormant)
        for child in (first, held, last):
            seq.AddAI(child)
        _install(ship, seq)
        return _scene_of(mp, [ship], {40: lambda: cond.SetStatus(1),
                                      90: lambda: cond.SetStatus(0),
                                      140: lambda: cond.SetStatus(1)})
    return build


@pytest.mark.parametrize("skip_dormant", [0, 1])
@pytest.mark.parametrize("loops", [2, -1])
def test_sequence_ai_skip_dormant_and_loops(skip_dormant, loops):
    rec = awd.run_walk_diff(_sequence(skip_dormant, loops), 360)
    indices = {s for s in _states(rec, "_current_index")
               if s != awd._ABSENT}
    assert len(indices) >= 3, indices                # walked the whole list
    remaining = {s for s in _states(rec, "_loops_remaining")
                 if s != awd._ABSENT}
    if loops == 2:
        assert ("int", 1) in remaining, remaining     # wrapped once
        assert _count(rec, "ship.ClearAI") == 1        # US_DONE tears down
        assert _count(rec, "fire_ai_done") == 1
    else:
        assert ("int", -1) in remaining
        assert _count(rec, "ship.ClearAI") == 0


# ── BuilderAI whose BuilderCreate raises (and one that builds) ───────────────

def _builder_scene(mp):
    ships = []
    made = {}

    def module(**funcs):
        mod = types.ModuleType("_awd_builder_%d" % len(made))
        for k, v in funcs.items():
            setattr(mod, k, v)
        sys.modules[mod.__name__] = mod
        mp.setitem(made, mod.__name__, mod)
        return mod.__name__

    bad = _ship("Bad")

    def Create1(pShip):
        return _leaf(pShip, "BuiltFirst")

    def Create2(pShip, dep):
        raise RuntimeError("BuilderCreate2 failed")
    bad_mod = module(BuilderCreate1=Create1, BuilderCreate2=Create2)
    b1 = _ai().BuilderAI_Create(bad, "BadBuilder", bad_mod)
    b1.AddAIBlock("one", "BuilderCreate1")
    b1.AddAIBlock("two", "BuilderCreate2")
    b1.AddDependency("two", "one")
    _install(bad, _plist(bad, "BadRoot", (1, b1),
                         (2, _leaf(bad, "Fallback", interval=0.1))))

    good = _ship("Good")

    def Make1(pShip):
        return _leaf(pShip, "G1", interval=0.05)

    def Make2(pShip, first):
        seq = _ai().SequenceAI_Create(pShip, "G2")
        seq.SetLoopCount(-1)
        seq.AddAI(first)
        return seq
    good_mod = module(BuilderCreate1=Make1, BuilderCreate2=Make2)
    b2 = _ai().BuilderAI_Create(good, "GoodBuilder", good_mod)
    b2.AddAIBlock("one", "BuilderCreate1")
    b2.AddAIBlock("two", "BuilderCreate2")
    b2.AddDependency("two", "one")
    b2._preprocessing_instance = Pre(b2, interval=0.1)
    b2._preprocessing_method = "PreUpdate"
    _install(good, b2)
    ships += [bad, good]
    return _scene_of(mp, ships)


def test_builder_ai_whose_builder_create_raises():
    rec = awd.run_walk_diff(_builder_scene, 120)
    assert _count(rec, "builder.BuilderCreate1") == 2          # both ships
    assert _count(rec, "builder.BuilderCreate2") == 2
    failed = [s for s in _states(rec, "_activation_failed") if s is True]
    assert failed, "no BuilderAI activation failed"
    assert any(e == ("raise", "builder.BuilderCreate2", 
                     e[2], "RuntimeError")
               for e in rec.log() if e[0] == "raise")
    assert _count(rec, "script.PreUpdate") > 0


# ── re-entrancy: a callback that mutates the tree mid-walk ───────────────────

def _forceupdate_scene(mp):
    ship = _ship()
    holder = {}

    def leaf_hook(n):
        if n % 3 == 0:
            holder["pre"].ForceUpdate()          # the parent, from below

    def pre_hook(n):
        if n % 2 == 0:
            holder["leaf"].ForceUpdate()         # the child, from above
    leaf = _leaf(ship, "Leaf", interval=0.5, on_update=leaf_hook)
    pre = _pre(ship, "Pre", leaf, interval=0.2, on_update=pre_hook)
    holder.update(leaf=leaf, pre=pre)
    _install(ship, pre)
    return _scene_of(mp, [ship])


def test_script_update_calls_force_update_on_another_node():
    rec = awd.run_walk_diff(_forceupdate_scene, 200)
    assert _count(rec, "node.ForceUpdate") >= 6, rec.calls()
    assert _count(rec, "script.Update") > 5


def _reset_scene(mp):
    ship = _ship()
    holder = {}

    def pre_hook(n):
        holder["leaf"].Reset()                   # ResetOnTargetChange's shape
    leaf = _leaf(ship, "Leaf", interval=0.5)
    pre = _pre(ship, "Pre", leaf, interval=0.1, on_update=pre_hook)
    holder["leaf"] = leaf
    _install(ship, pre)
    return _scene_of(mp, [ship])


def test_preprocessor_resets_its_contained_ai():
    rec = awd.run_walk_diff(_reset_scene, 200)
    resets = _count(rec, "node.Reset")
    assert resets >= 15, rec.calls()
    assert _count(rec, "script.Reset") == resets     # the script heard each
    # Reset re-opened the leaf's 0.5 s gate every 0.1 s: it ran about once
    # per reset, not once per 0.5 s (which would be ~7 times in 200 ticks).
    assert _count(rec, "script.Update") >= resets - 1


def _set_ai_scene(mp):
    ship = _ship()

    def second_tree():
        return _plist(ship, "Second", (1, _leaf(
            ship, "L2", interval=0.02,
            on_update=lambda n: ship.ClearAI() if n == 6 else None)))

    clock = {"t": 0.0}

    def first_hook(n):
        if n == 5:
            new = second_tree()
            ship.SetAI(new)                      # a script replaces its own tree
            # ...and walks it at once, so the brand-new nodes run THIS tick.
            _driver().tick_ai(new, clock["t"])
    first = _plist(ship, "First", (1, _leaf(
        ship, "L1", interval=0.02, on_update=first_hook)))
    _install(ship, first)

    def step(i):
        clock["t"] = (i + 1) / 60.0
        _driver().tick_all_ai(clock["t"])
    return awd.synthetic_scene(mp, [ship], step)


def test_script_sets_and_clears_the_ai_of_its_own_ship():
    rec = awd.run_walk_diff(_set_ai_scene, 80)
    assert _count(rec, "ship.SetAI") == 1
    assert _count(rec, "ship.ClearAI") == 1
    assert _count(rec, "fire_ai_done") == 2          # the old tree, then the new
    assert _count(rec, "script.Update") >= 10
    # The new tree's leaf ran, and was logged, in the SAME tick as the SetAI.
    tick = next(log for log, _s in rec.ticks
                if any(e[:2] == ("call", "ship.SetAI") for e in log))
    names = [e[1] for e in tick]
    after = tick[names.index("ship.SetAI"):]
    assert any(e[:2] == ("call", "script.Update") for e in after), after


def _add_ai_scene(mp):
    ship = _ship()
    holder = {}

    def scan_eval(bOn):
        # Called from _refresh_conditional_status while the PriorityList scan
        # is iterating its live list: AddAI appends AND sorts in place.
        holder["evals"] = holder.get("evals", 0) + 1
        if holder["evals"] == 9:
            holder["root"].AddAI(holder["extra"], 1)
        return US_DORMANT

    cond = _cond(1)
    gate = _ai().ConditionalAI_Create(ship, "Gate")
    gate.AddCondition(cond)
    gate.SetEvaluationFunction(scan_eval)
    gate.SetContainedAI(_leaf(ship, "Hidden"))

    def remove_hook(n):
        if n == 4:
            holder["root"].RemoveAI(holder["extra"])     # rebinds the list
    holder["extra"] = _leaf(ship, "Extra", interval=0.02, on_update=remove_hook)
    root = _plist(ship, "Root", (1, gate),
                  (2, _leaf(ship, "Low", interval=0.05)),
                  (3, _leaf(ship, "Lowest", interval=0.05)))
    holder["root"] = root
    _install(ship, root)
    return _scene_of(mp, [ship])


def test_add_ai_on_a_priority_list_being_scanned():
    rec = awd.run_walk_diff(_add_ai_scene, 120)
    assert _count(rec, "eval") >= 9, rec.calls()
    sizes = [len(s) - 1 for s in _states(rec, "_ais")
             if s != awd._ABSENT]               # ('list', child, ...)
    assert max(sizes) == 4 and min(sizes) == 3, set(sizes)
    assert sizes[-1] == 3, "the extra child was never removed again"
    assert _count(rec, "script.Update") > 4
    # AddAI(priority 1) sorts the extra child behind the gate being scanned, so
    # the live scan reaches it in the same tick: its Update must be logged
    # there, after the AddAI.
    tick = next(log for log, _s in rec.ticks
                if any(e[:2] == ("call", "node.AddAI") for e in log))
    names = [e[1] for e in tick]
    added = next(e for e in tick if e[:2] == ("call", "node.AddAI"))[3][1]
    assert added[0] == "ai", added                  # the AddAI's node argument
    after = tick[names.index("node.AddAI"):]
    # The ADDED node's own script Update (a hook logs under its node's ID).
    assert any(e[:2] == ("call", "script.Update") and e[2] == ("int", added[1])
               for e in after), (added, after)


# ── escaping exceptions ──────────────────────────────────────────────────────

class _Boom(Exception):
    pass


def _escape_scene(mp):
    drv = _driver()
    ships = []

    def single(name, interval=0.0, **kw):
        ship = _ship(name)
        _install(ship, _plist(ship, name + "Root",
                              (1, _leaf(ship, name + "Leaf",
                                        interval=interval, **kw))))
        ships.append(ship)
        return ship

    # 1: GetNextUpdateTime raises on its 3rd call
    calls = {"g": 0}
    s1 = single("NextTime")
    leaf1 = s1.GetAI()._ais[0][1]

    def raising_next():
        calls["g"] += 1
        if calls["g"] == 3:
            raise _Boom("GetNextUpdateTime")
        return 0.0
    leaf1._script_instance.GetNextUpdateTime = raising_next

    # 2: int(status) raises on the 4th Update
    s2 = single("IntStatus")
    leaf2 = s2.GetAI()._ais[0][1]
    inst2 = leaf2._script_instance
    real_update = inst2.Update

    def bad_status():
        real_update()
        return "not-a-status" if inst2.n == 4 else US_ACTIVE
    inst2.Update = bad_status

    # 3: IsInterruptable raises on the contained node of a preprocessor
    s3 = _ship("Interruptable")
    inner = _leaf(s3, "Inner", interval=0.5)
    inner._interruptable = False
    n3 = {"n": 0}

    def raising_interruptable():
        n3["n"] += 1
        if n3["n"] == 5:
            raise _Boom("IsInterruptable")
        return False
    inner.IsInterruptable = raising_interruptable
    _install(s3, _pre(s3, "Pre3", inner, interval=0.3))
    ships.append(s3)

    # 4: the out-of-action gate raises once (patched by the scene, wrapped
    # by the harness, reached through ai_driver.ship_death)
    s4 = single("Gate")
    import engine.appc.ship_death as sd
    real_ooa = sd._out_of_action
    n4 = {"n": 0}

    def flaky_ooa(ship):
        if ship is s4:
            n4["n"] += 1
            if n4["n"] == 7:
                raise _Boom("_out_of_action")
        return real_ooa(ship)
    mp.setattr(sd, "_out_of_action", flaky_ooa)

    # 5: a script Update that raises is SWALLOWED and reported once
    s5 = single("Swallowed", interval=0.0)
    inst5 = s5.GetAI()._ais[0][1]._script_instance

    def raising_update():
        raise _Boom("Update")
    inst5.Update = raising_update
    return _scene_of(mp, ships)


def test_exceptions_escaping_the_walk_and_swallowed_ones():
    rec = awd.run_walk_diff(_escape_scene, 80)
    escaped = [e[1] for e in rec.log() if e[0] == "escaped"]
    assert sorted(escaped) == ["ValueError", "_Boom", "_Boom", "_Boom"], escaped
    assert [e[2] for e in rec.log() if e[0] == "escaped" and e[1] == "_Boom"] \
        == ["GetNextUpdateTime", "_out_of_action", "IsInterruptable"]
    errors = rec.ticks[-1][1]["errors"]
    assert any(k[1] == "_Boom" for k in errors), errors      # swallowed once
    assert len([k for k in errors if k[1] == "_Boom"]) == 1


# ── nested root walks ────────────────────────────────────────────────────────

def _nested_scene(mp):
    drv = _driver()
    clock = {"t": 1 / 60.0}
    other = _ship("Other")
    other_root = _plist(other, "OtherRoot",
                        (1, _leaf(other, "OtherLeaf", interval=0.0)))
    _install(other, other_root)

    ship = _ship("Main")

    def got_focus_hook():
        # GotFocus runs after the outer root's depth is back to 0, so this
        # tick_ai is itself a ROOT walk (it rebinds the module walk state).
        drv.tick_ai(other_root, clock["t"])

    def update_hook(n):
        # Mid-walk (depth > 0): a nested, non-root call into another tree.
        if n % 4 == 0:
            drv.tick_ai(other_root, clock["t"])

    leaf = _leaf(ship, "Leaf", interval=0.02, on_update=update_hook)
    pre = _pre(ship, "Pre", leaf, interval=0.1)
    hooked = pre._preprocessing_instance
    hooked.GotFocus = got_focus_hook
    hooked.LostFocus = lambda: drv.tick_ai(other_root, clock["t"])
    gate = _ai().ConditionalAI_Create(ship, "Gate")
    gate._status = US_DORMANT                   # until tick 60 takes the path
    root = _plist(ship, "MainRoot", (1, gate), (2, pre))
    _install(ship, root)
    # the second ship runs too, so a clobbered walk state would be seen
    follower = _ship("Follower")
    _install(follower, _plist(follower, "FRoot", (1, _leaf(
        follower, "FLeaf", interval=0.0))))

    def step(i):
        clock["t"] = (i + 1) / 60.0
        if i == 60:                     # the pre drops off the path: LostFocus
            gate._status = US_ACTIVE
        drv.tick_all_ai(clock["t"])
    return awd.synthetic_scene(mp, [ship, follower], step,
                               extra_ships=[other])


def test_nested_root_walk_from_focus_and_update_hooks():
    rec = awd.run_walk_diff(_nested_scene, 120)
    assert _count(rec, "script.GotFocus") >= 1, rec.calls()
    assert _count(rec, "script.LostFocus") >= 1, rec.calls()
    assert _count(rec, "script.Update") > 10

    def nested(hook):
        """Walks of the OTHER ship's tree (its out-of-action gate runs at each
        node) recorded between a hook's call and its return."""
        depth, found = 0, 0
        for e in rec.log():
            if e[:2] == ("call", hook):
                depth += 1
            elif e[:2] in (("ret", hook), ("raise", hook)):
                depth -= 1
            elif (depth and e[:2] == ("call", "_out_of_action")
                    and e[2] == ("obj", "ShipClass", "Other")):
                found += 1
        return found
    assert nested("script.GotFocus") >= 1      # a root walk from GotFocus
    assert nested("script.LostFocus") >= 1
    assert nested("script.Update") >= 1        # a non-root walk from Update


# ── a node type outside the stock set, and a patched stock handler ───────────

def _injected_scene(mp):
    drv = _driver()
    ArtificialIntelligence = _ai().ArtificialIntelligence

    class Gate(ArtificialIntelligence):
        """A test node type: not a subclass of any stock container."""
        def __init__(self, ship, name, child):
            super().__init__(ship, name)
            self._child = child
            self._contained_ai = child       # so the harness finds the subtree

    def gate_handler(ai, game_time):
        ai.IsInterruptable()                      # logged: proves it ran
        drv.tick_ai(ai._child, game_time)
        ai._status = ai._child._status
        return ai._status

    mp.setitem(drv._DISPATCH_BY_TYPE, Gate, gate_handler)
    PlainAI = _ai().PlainAI
    stock = drv._tick_plain

    def patched_plain(ai, game_time):
        ai.IsInterruptable()
        return stock(ai, game_time)
    mp.setitem(drv._DISPATCH_BY_TYPE, PlainAI, patched_plain)

    ship = _ship()
    leaf = _leaf(ship, "Leaf", interval=0.05, done_after=40)
    gate = Gate(ship, "Gate", leaf)
    _install(ship, gate)
    return _scene_of(mp, [ship])


def test_injected_node_type_and_patched_stock_handler_are_honoured():
    rec = awd.run_walk_diff(_injected_scene, 120)
    # Gate handler + patched PlainAI handler each log an IsInterruptable.
    walks = _count(rec, "script.Update")
    assert walks >= 20, rec.calls()
    assert _count(rec, "node.IsInterruptable") >= 2 * walks, rec.calls()


# ── the roster and its sleep scheduling (Task 2: native roster) ─────────────

def _walked_ticks(rec, name):
    """Ticks in which ship `name`'s tree was walked: its out-of-action gate
    (called at the root of every walk) was logged for it."""
    who = ("obj", "ShipClass", name)
    return [t for t, (log, _s) in enumerate(rec.ticks)
            if any(e[:2] == ("call", "_out_of_action") and e[2] == who
                   for e in log)]


def _sleeper_scene(mp):
    """A ship whose only leaf runs every 0.5 s sleeps to the 4-tick cap; an
    every-tick ship beside it is walked every tick."""
    sleeper = _ship("Sleeper")
    _install(sleeper, _plist(sleeper, "SRoot",
                             (1, _leaf(sleeper, "Slow", interval=0.5))))
    awake = _ship("Awake")
    _install(awake, _plist(awake, "ARoot", (1, _leaf(awake, "Fast"))))
    return _scene_of(mp, [sleeper, awake])


def test_scheduler_skips_a_ship_while_it_sleeps():
    rec = awd.run_walk_diff(_sleeper_scene, 60)
    slept = _walked_ticks(rec, "Sleeper")
    assert 12 <= len(slept) <= 16, slept               # capped at 4 ticks
    assert _walked_ticks(rec, "Awake") == list(range(60))
    stamps = {s["ships"][repr(("obj", "ShipClass", "Sleeper"))]["walk_due"]
              for _l, s in rec.ticks}
    assert len(stamps) >= 12, stamps                   # stamped each walk


def _stale_stamp_scene(mp):
    """A stamp from an earlier mission (game time restarted) lies far above
    the upper bound and must not freeze the ship; one just inside the bound
    is honoured."""
    ship = _ship("Stale")
    _install(ship, _plist(ship, "Root", (1, _leaf(ship, "L", interval=0.5))))

    def stale():
        ship.__dict__["_ai_next_walk_due"] = 300.0

    def inside():
        ship.__dict__["_ai_next_walk_due"] = 31 / 60.0 + 3.5 / 60.0
    return _scene_of(mp, [ship], {0: stale, 10: stale, 30: inside})


def test_scheduler_ignores_a_stale_stamp_above_the_upper_bound():
    rec = awd.run_walk_diff(_stale_stamp_scene, 40)
    walked = _walked_ticks(rec, "Stale")
    assert 0 in walked and 10 in walked, walked        # the stale stamp
    assert 30 not in walked and 31 not in walked, walked   # honoured
    assert any(t > 31 for t in walked), walked


def _set_ai_while_asleep_scene(mp):
    """SetAI on a sleeping ship: the new tree waits out the stamp (SetAI
    sends no wake), then runs."""
    ship = _ship("Swap")
    _install(ship, _plist(ship, "Old", (1, _leaf(ship, "OldLeaf",
                                                 interval=0.5))))

    def swap():
        ship.SetAI(_plist(ship, "New", (1, _leaf(ship, "NewLeaf",
                                                 interval=0.0))))
    return _scene_of(mp, [ship], {2: swap})


def test_scheduler_set_ai_on_a_sleeping_ship():
    rec = awd.run_walk_diff(_set_ai_while_asleep_scene, 20)
    walked = _walked_ticks(rec, "Swap")
    assert walked[0] == 0 and 2 not in walked, walked  # asleep at the SetAI
    assert _count(rec, "ship.SetAI") == 1
    assert _count(rec, "fire_ai_done") == 1            # the old tree's
    first_new = min(t for t in walked if t > 2)
    assert first_new <= 5, walked                      # the 4-tick cap
    assert walked[walked.index(first_new):] == list(range(first_new, 20))


def _done_scene(mp):
    """Root completion: a tree that ends is torn down by ClearAI, which
    announces ET_AI_DONE once; a tree whose last Update installs a successor
    is NOT cleared (the still-installed check); a bare ship without ClearAI
    gets fire_ai_done directly. The done trees are asleep-capable (0.05 s)."""
    done = _ship("Done")
    seq = _ai().SequenceAI_Create(done, "Once")
    seq.SetLoopCount(1)
    seq.AddAI(_leaf(done, "Finish", done_after=3, interval=0.05))
    _install(done, seq)

    handed = _ship("Handed")

    def hand_over(n):
        if n == 2:
            handed.SetAI(_plist(handed, "Next",
                                (1, _leaf(handed, "NextLeaf", interval=0.1))))
    seq2 = _ai().SequenceAI_Create(handed, "Hands")
    seq2.SetLoopCount(1)
    seq2.AddAI(_leaf(handed, "Last", done_after=2, interval=0.05,
                     on_update=hand_over))
    _install(handed, seq2)

    class Bare:
        """A test double without ClearAI (the fire_ai_done fallback)."""
        def __init__(self, name):
            self._n = name
            self._ai = None

        def GetName(self):
            return self._n

        def GetAI(self):
            return self._ai

        def IsDying(self):
            return False

        def IsDead(self):
            return False
    bare = Bare("Bare")
    bare_root = _ai().SequenceAI_Create(None, "BareRoot")
    bare_root.SetLoopCount(1)
    bare_root.AddAI(_leaf(None, "BareLeaf", done_after=2))
    bare._ai = bare_root
    return _scene_of(mp, [done, handed, bare])


def test_scheduler_clear_ai_fires_ai_done_once():
    rec = awd.run_walk_diff(_done_scene, 40)
    calls = rec.log()
    clears = [e for e in calls if e[:2] == ("call", "ship.ClearAI")]
    assert [e[2] for e in clears] == [("tuple", "ship", "Done")], clears
    dones = [e[2] for e in calls if e[:2] == ("call", "fire_ai_done")]
    # Done's ClearAI, Handed's SetAI (the old tree), the bare ship's direct
    # call: each tree announced exactly once.
    assert sorted(map(repr, dones)) == sorted(map(repr, set(dones))), dones
    assert len(dones) == 3, dones
    last = rec.ticks[-1][1]["ships"]
    assert last[repr(("obj", "ShipClass", "Done"))]["ai"] is None
    assert last[repr(("obj", "ShipClass", "Handed"))]["ai"] is not None


def _roster_glue_scene(mp):
    """The defensive-cloak skip, a monkeypatched sleep cap and tick length,
    and an int stamp (min() keeps the int when it is the smaller)."""
    from engine.appc import defensive_cloak
    drv = _driver()
    hidden = _ship("Hidden")
    _install(hidden, _plist(hidden, "HRoot", (1, _leaf(hidden, "HL"))))
    timed = _ship("Timed")
    leaf = _leaf(timed, "TL", interval=0.5)
    _install(timed, _plist(timed, "TRoot", (1, leaf)))
    real = defensive_cloak.is_defensive
    mp.setattr(defensive_cloak, "is_defensive",
               lambda ship: (ship is hidden and 5 <= clock["i"] < 12)
               or real(ship))
    mp.setattr(drv, "AI_MAX_SLEEP_TICKS", 6)
    clock = {"i": 0}

    def step(i):
        clock["i"] = i
        if i == 20:
            mp.setattr(drv, "_TICK_SECONDS", 1.0 / 30.0)
        if i == 40:
            # an int due time between now and the cap: the stamp keeps it
            leaf._next_update_time = 1
        drv.tick_all_ai(0.3 + (i + 1) / 60.0 if i >= 40 else (i + 1) / 60.0)
    return awd.synthetic_scene(mp, [hidden, timed], step)


def test_scheduler_defensive_skip_patched_cap_and_int_stamp():
    rec = awd.run_walk_diff(_roster_glue_scene, 60)
    hidden = _walked_ticks(rec, "Hidden")
    assert not set(range(5, 12)) & set(hidden), hidden
    assert set(range(0, 5)) <= set(hidden), hidden
    stamps = [s["ships"][repr(("obj", "ShipClass", "Timed"))]["walk_due"]
              for _l, s in rec.ticks]
    assert ("int", 1) in stamps, stamps


def _min_tie_scene(mp):
    """The stamp's min() on a tie: an int due time equal to the float cap is
    kept (builtin min returns its FIRST argument unless the second is
    smaller), so the stamp is the int 1, not 1.0."""
    drv = _driver()
    ship = _ship("Tie")
    leaf = _leaf(ship, "L", interval=0.5)
    leaf._next_update_time = 1                 # an int due time
    _install(ship, _plist(ship, "Root", (1, leaf)))
    mp.setattr(drv, "AI_MAX_SLEEP_TICKS", 4)
    mp.setattr(drv, "_TICK_SECONDS", 0.125)    # cap = 0.5 + 4 * 0.125 = 1.0

    def step(i):
        drv.tick_all_ai(0.5 + i)
    return awd.synthetic_scene(mp, [ship], step)


def test_scheduler_min_keeps_the_noted_due_on_a_tie():
    rec = awd.run_walk_diff(_min_tie_scene, 2)
    stamp = rec.ticks[0][1]["ships"][repr(("obj", "ShipClass", "Tie"))]
    assert stamp["walk_due"] == ("int", 1), stamp["walk_due"]


def _roster_escape_scene(mp):
    """Exceptions escaping the roster itself: is_defensive raising for the
    second ship, GetAI raising, a ClearAI raising after US_DONE. Each skips
    the stamp (where reached) and every later ship for that tick."""
    from engine.appc import defensive_cloak
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    for s in (a, b, c):
        _install(s, _plist(s, s.GetName() + "Root",
                           (1, _leaf(s, s.GetName() + "L", interval=0.0))))
    real = defensive_cloak.is_defensive
    clock = {"i": 0}

    def flaky(ship):
        if ship is b and clock["i"] == 3:
            raise _Boom("is_defensive")
        return real(ship)
    mp.setattr(defensive_cloak, "is_defensive", flaky)
    real_get = b.GetAI
    raised = []

    def get_ai():
        # Once: the roster's call (the harness's own reads come before the
        # tick's clock moves, or after the raise).
        if clock["i"] == 6 and not raised:
            raised.append(1)
            raise _Boom("GetAI")
        return real_get()
    b.GetAI = get_ai
    seq = _ai().SequenceAI_Create(a, "AOnce")
    seq.SetLoopCount(1)
    seq.AddAI(_leaf(a, "AFinal", done_after=1))

    def clear_raises():
        raise _Boom("ClearAI")

    def arm():
        a.SetAI(seq)
        a.ClearAI = clear_raises

    def step(i):
        clock["i"] = i
        if i == 9:
            arm()
        _driver().tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, [a, b, c], step)


def test_scheduler_exceptions_escaping_the_roster():
    rec = awd.run_walk_diff(_roster_escape_scene, 14)
    escaped = [e[2] for e in rec.log() if e[0] == "escaped"]
    assert escaped == ["is_defensive", "GetAI", "ClearAI"], escaped
    c_walked = _walked_ticks(rec, "C")
    assert 3 not in c_walked and 6 not in c_walked and 9 not in c_walked
    assert 4 in c_walked and 7 in c_walked


# ── frame-local lifetimes: when the roster's locals let go ──────────────────
#
# The Python roster's locals (ship, due, ai, status, get_ai, clear) keep their
# objects until the NEXT assignment to the same name (STORE_FAST: the new
# value stored, then the old one released), or until the function returns.
# A finaliser (SDK conditions tear down in __del__) runs at that point, so
# the native roster must release at the same points. These probes record
# their own __del__ into the call log, and hold no reference cycle (an AI
# root lists itself in _active_nodes, which would leave its death to the
# cyclic collector).

class _Status(int):
    """A tick status that records its own release."""

    def __del__(self):
        awd.mark(self.owner, "del status", self.tag)


class _Stamp(float):
    """A sleep stamp that records its own release."""

    def __del__(self):
        awd.mark(self.owner, "del stamp", self.tag)


class _ProbeRoot:
    """A cycle-free foreign root: the driver's writes of node lists and the
    harness's instrumenting wrappers are dropped, so only the roster's local,
    the ship and the driver's per-root scratch hold it."""

    def __init__(self, ident, name, script):
        object.__setattr__(self, "_id", ident)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_script", script)
        object.__setattr__(self, "_owner", awd.current())
        object.__setattr__(self, "_status", US_ACTIVE)

    def __setattr__(self, k, v):
        if k == "_active_nodes" or callable(v):
            return
        object.__setattr__(self, k, v)

    def GetID(self):
        return self._id

    def GetName(self):
        return self._name

    def SetActive(self, *a):
        pass

    def SetInactive(self, *a):
        pass

    def __del__(self):
        awd.mark(self._owner, "del root", self._name)


def _lifetime_scene(mp):
    """A: its root ends (US_DONE) and the roster ClearAIs it. B: its root's
    second walk replaces it with SetAI. C: a plain follower. Every tick each
    of A and B gets a fresh probe stamp in the past (so it is walked, and the
    stamp is then held only by the roster's `due`), and every probe walk
    returns a fresh probe status (held only by `status`)."""
    drv = _driver()
    owner = awd.current()
    clock = {"i": 0}

    def status(value, tag):
        st = _Status(value)
        st.owner, st.tag = owner, tag
        return st

    a, b, c = _ship("A"), _ship("B"), _ship("C")

    def a_script(root, n):
        return status(US_DONE, "A%d" % clock["i"])

    def b_script(root, n):
        if n == 2:
            b.SetAI(_ProbeRoot(9_100_003, "PB2", b_script))
        return status(US_ACTIVE, "B%d" % clock["i"])

    calls = {}

    def handler(ai, game_time):
        calls[ai._id] = calls.get(ai._id, 0) + 1
        return ai._script(ai, calls[ai._id])
    mp.setitem(drv._DISPATCH_BY_TYPE, _ProbeRoot, handler)
    a.SetAI(_ProbeRoot(9_100_001, "PA", a_script))
    b.SetAI(_ProbeRoot(9_100_002, "PB", b_script))
    _install(c, _plist(c, "CRoot", (1, _leaf(c, "CL"))))

    def stamp(ship, i):
        st = _Stamp(0.0)
        st.owner, st.tag = owner, "%s%d" % (ship.GetName(), i)
        ship.__dict__["_ai_next_walk_due"] = st

    def step(i):
        clock["i"] = i
        stamp(a, i)
        stamp(b, i)
        drv.tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, [a, b, c], step)


def test_roster_locals_are_released_where_python_releases_them():
    rec = awd.run_walk_diff(_lifetime_scene, 6)
    marks = [e[1:] for e in rec.log() if e[0] == "mark"]
    kinds = {m[0] for m in marks}
    assert kinds == {"del status", "del stamp", "del root"}, marks
    # B's tick-0 status lives until the NEXT walked ship's status (C's) is
    # stored, so it is released after C's is_defensive call, not at the end of
    # B's iteration.
    tick0 = rec.ticks[0][0]
    names = [(e[0], e[1], e[2] if len(e) > 2 else None) for e in tick0]
    del_b0 = names.index(("mark", "del status", "B0"))
    c_def = next(k for k, e in enumerate(tick0)
                 if e[:2] == ("call", "is_defensive")
                 and e[2] == ("obj", "ShipClass", "C"))
    assert c_def < del_b0, tick0
    assert ("del root", "PA") in marks and ("del root", "PB") in marks


def _root_lifetime_scene(mp):
    """The `ai` local itself. A real root walk keeps the root alive in the
    driver's per-root scratch until the next root walk, which masks when
    the roster lets go, so here the probe roots skip the walk (tick_ai is
    replaced for them, read per call by both rosters). A: its root ends and
    is ClearAI'd. B: its root ends after installing a successor (the
    not-still-installed path). C: a real tree after both."""
    drv = _driver()
    real_tick_ai = drv.tick_ai
    a, b, c = _ship("A"), _ship("B"), _ship("C")
    made = {"n": 0}

    def tick_ai(ai, game_time):
        if not isinstance(ai, _ProbeRoot):
            return real_tick_ai(ai, game_time)
        if ai._name.startswith("PB"):
            made["n"] += 1
            b.SetAI(_ProbeRoot(9_200_010 + made["n"], "PB%d" % made["n"],
                               None))
        return US_DONE
    mp.setattr(drv, "tick_ai", tick_ai)
    a.SetAI(_ProbeRoot(9_200_001, "PA", None))
    b.SetAI(_ProbeRoot(9_200_002, "PB0", None))
    _install(c, _plist(c, "CRoot", (1, _leaf(c, "CL"))))
    return _scene_of(mp, [a, b, c])


def test_roster_releases_a_cleared_or_replaced_root_where_python_does():
    rec = awd.run_walk_diff(_root_lifetime_scene, 4)
    tick0 = rec.ticks[0][0]
    del_pa = tick0.index(("mark", "del root", "PA"))
    # Python's `ai` holds A's cleared root until B's GetAI rebinds it: after
    # B's is_defensive, not at the end of A's iteration.
    b_def = next(k for k, e in enumerate(tick0)
                 if e[:2] == ("call", "is_defensive")
                 and e[2] == ("obj", "ShipClass", "B"))
    assert b_def < del_pa, tick0
    marks = [e[1:] for e in rec.log() if e[0] == "mark"]
    assert ("del root", "PB0") in marks, marks


# ── condition evaluation (S2) ────────────────────────────────────────────────
#
# The native side evaluates conditions natively from Task 3 on: the priority
# list's and the sequence's refresh, _tick_conditional's status reads and
# _eval_conditional (memo included). The harness proves the native side ran it
# (aitree_conditional_counts) and never the Python bodies.

def _s2_scene_of(mp, ships, actions=None, wrap_status=True):
    actions = actions or {}

    def step(i):
        if i in actions:
            actions[i]()
        _driver().tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, ships, step,
                               wrap_condition_status=wrap_status)


def _gated(ship, name, conds, fn, contained):
    node = _ai().ConditionalAI_Create(ship, name)
    for c in conds:
        node.AddCondition(c)
    if fn is not None:
        node.SetEvaluationFunction(fn)
    if contained is not None:
        node.SetContainedAI(contained)
    return node


def _raising_eval_scene(mp):
    """EvalFuncs that raise. Transient: memoisable (defaults, no globals), so
    the retry after a raise is what the memo must not hide; an exception maps
    to US_DORMANT and is never cached. Alternating: declined by the gate,
    raises every other call. A second ship's EvalFunc returns a value int()
    rejects, which is OUTSIDE the try and escapes the walk."""
    ship = _ship()
    c1, c2 = _cond(1), _cond(1)

    def Transient(b, n=[0], ACTIVE=US_ACTIVE, Boom=_Boom):
        n[0] += 1
        if n[0] in (2, 3, 7):
            raise Boom("transient")
        return ACTIVE

    def Alternating(b, n=[0]):
        n[0] += 1
        if n[0] % 2:
            raise KeyError("alternating")
        return US_ACTIVE if b else US_DORMANT

    root = _plist(ship, "Root",
                  (1, _gated(ship, "T", [c1], Transient,
                             _leaf(ship, "TL"))),
                  (2, _gated(ship, "A", [c2], Alternating,
                             _leaf(ship, "AL"))),
                  (3, _leaf(ship, "Idle")))
    _install(ship, root)

    bad = _ship("Bad")
    cb = _cond(1)

    seen = {"n": 0}

    def Unparseable(b):                 # a closure: declined, so re-run
        seen["n"] += 1
        return "not-a-status" if seen["n"] == 4 else 0
    _install(bad, _plist(bad, "BadRoot", (1, _gated(
        bad, "B", [cb], Unparseable, _leaf(bad, "BL")))))
    # Every flip of c1 is a memo miss for Transient (a fresh key), so it is
    # called, and raises on its 2nd, 3rd and 7th calls; the dormant ticks
    # that follow a raise let the scan reach Alternating.
    actions = {i: (lambda v=i % 2: c1.SetStatus(v)) for i in range(2, 30, 3)}
    actions[31] = lambda: c2.SetStatus(0)
    return _s2_scene_of(mp, [ship, bad], actions)


def test_conditional_an_evalfunc_that_raises():
    rec = awd.run_walk_diff(_raising_eval_scene, 40)
    raised = [e for e in rec.log() if e[0] == "raise" and e[1] == "eval"]
    assert [e[3] for e in raised].count("_Boom") == 3, raised
    assert [e[3] for e in raised].count("KeyError") >= 2, raised
    escaped = [e[1] for e in rec.log() if e[0] == "escaped"]
    assert escaped == ["ValueError"], escaped
    assert rec.native_entries["native_s2"] > 0, rec.native_entries


def _chainfollow_scene(mp):
    """ChainFollow's EvalFunc shape: it reads a module global (iIndex), so the
    memo gate declines it and it runs on every refresh; the scene moves the
    global with the conditions held steady. A memoisable sibling is cached."""
    ship = _ship()
    ns = {}
    exec(compile("iIndex = 0\n"
                 "def EvalFunc(bShipExists):\n"
                 "    if (iIndex <= 7) or not bShipExists:\n"
                 "        return 2\n"
                 "    return 0\n", "<chainfollow-like>", "exec"), ns)
    cond, steady = _cond(1), _cond(1)

    def Pure(b, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        return ACTIVE if b else DORMANT

    root = _plist(ship, "Root",
                  (1, _gated(ship, "Chain", [cond], ns["EvalFunc"],
                             _leaf(ship, "Follow"))),
                  (2, _gated(ship, "Pure", [steady], Pure,
                             _leaf(ship, "PureLeaf", interval=0.05))))
    _install(ship, root)

    def move(v):
        ns["iIndex"] = v
    return _s2_scene_of(mp, [ship], {6: lambda: move(9), 12: lambda: move(3),
                                     18: lambda: move(8)})


def test_conditional_a_non_memoisable_evalfunc():
    rec = awd.run_walk_diff(_chainfollow_scene, 30)
    assert _count(rec, "eval") >= 30, rec.calls()
    caches = [st["_evalfn_cache"] for _log, snap in rec.ticks
              for ship in snap["ships"].values()
              for st in ship["nodes"].values() if st["type"] == "ConditionalAI"]
    assert any(c != awd._ABSENT for c in caches)        # Pure is cached
    statuses = _states(rec, "_status")
    assert ("int", US_DORMANT) in statuses and ("int", US_ACTIVE) in statuses


def _custom_status_scene(mp):
    """A condition class with its own GetStatus, an instance whose dict
    shadows the stock GetStatus, a class-level patch of TGCondition.GetStatus
    mid-run, and stock conditions read directly. Nothing is wrapped: each
    non-stock GetStatus marks its own call, so the order is in the log."""
    ai = _ai()
    owner = awd.current()

    class OwnStatus(ai.TGCondition):
        def __init__(self):
            super().__init__()
            self.n = 0

        def GetStatus(self):
            self.n += 1
            awd.mark(owner, "own", self.GetObjID(), self.n)
            return (self.n // 3) % 2        # flips every third read

    ship = _ship()
    own = OwnStatus()
    shadowed = _cond(0)
    flips = {"n": 0}

    def shadow():
        flips["n"] += 1
        awd.mark(owner, "shadow", flips["n"])
        return flips["n"] % 2
    shadowed.GetStatus = shadow
    stock_a, stock_b = _cond(1), _cond(0)

    def Both(a, b, c, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        return ACTIVE if (a and (b or c)) else DORMANT

    real = ai.TGCondition.__dict__["GetStatus"]

    def patched(self):
        awd.mark(owner, "patched", self.GetObjID())
        return 1 - real(self)

    root = _plist(ship, "Root",
                  (1, _gated(ship, "Mixed", [stock_a, own, shadowed], Both,
                             _leaf(ship, "MixedLeaf"))),
                  (2, _gated(ship, "AnyRule", [stock_b, own], None,
                             _leaf(ship, "AnyLeaf"))),
                  (3, _leaf(ship, "Idle", interval=0.1)))
    _install(ship, root)
    return _s2_scene_of(
        mp, [ship], {8: lambda: stock_b.SetStatus(1),
                     16: lambda: mp.setattr(ai.TGCondition, "GetStatus",
                                            patched),
                     24: lambda: mp.setattr(ai.TGCondition, "GetStatus",
                                            real)},
        wrap_status=False)


def test_conditional_a_condition_class_with_its_own_get_status():
    rec = awd.run_walk_diff(_custom_status_scene, 30)
    kinds = Counter(e[1] for e in rec.log() if e[0] == "mark")
    assert kinds["own"] >= 20 and kinds["shadow"] >= 15, kinds
    assert kinds["patched"] >= 4, kinds
    assert _count(rec, "cond.GetStatus") == 0, rec.calls()
    assert rec.native_entries["stock_status_reads"] > 0, rec.native_entries


def _direct_status_scene(mp):
    """Stock conditions whose `_status` a test writes directly (no SetStatus,
    so no handler and no event): the refresh must still see each write. Covers
    the no-EvalFunc rule (any condition non-zero: ACTIVE, else DORMANT; no
    conditions: status untouched) on both the refresh and _tick_conditional,
    a condition-less conditional, the contained-DONE fold under a memo hit,
    a sequence's refresh, and a ConditionScript (stock GetStatus)."""
    ai = _ai()
    ship = _ship()
    a, b, c, d = _cond(0), _cond(0), _cond(1), _cond(0)
    script = ai.ConditionScript()            # no module: a stock data bag

    def Pure(x, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        return ACTIVE if x else DORMANT

    seq = ai.SequenceAI_Create(ship, "Seq")
    seq.SetSkipDormant(1)
    seq.SetLoopCount(-1)
    seq.AddAI(_gated(ship, "SeqGate", [d], None, _leaf(ship, "SeqLeaf",
                                                         done_after=2)))
    seq.AddAI(_leaf(ship, "SeqTail", done_after=1))
    root = _plist(ship, "Root",
                  (1, _gated(ship, "AnyRule", [a, b], None,
                             _leaf(ship, "AnyLeaf", done_after=4))),
                  (2, _gated(ship, "Folded", [c], Pure,
                             _leaf(ship, "FoldLeaf", done_after=3))),
                  (3, _gated(ship, "Script", [script], Pure,
                             _leaf(ship, "ScriptLeaf"))),
                  (4, _gated(ship, "Empty", [], None, _leaf(ship, "E"))),
                  (5, seq))
    _install(ship, root)
    lone = _ship("Lone")
    _install(lone, _gated(lone, "LoneRoot", [_cond(0)], None,
                          _leaf(lone, "LoneLeaf")))
    lone_cond = lone.GetAI()._conditions[0]

    def write(cond, v):
        cond._status = v
    return _s2_scene_of(mp, [ship, lone], {
        3: lambda: write(b, 5),
        6: lambda: write(b, 0),
        7: lambda: write(script, 1),
        9: lambda: write(a, -1),
        12: lambda: write(c, 0),
        13: lambda: write(c, 1),
        15: lambda: write(a, 0),
        16: lambda: write(d, 1),
        18: lambda: write(lone_cond, 1),
        24: lambda: write(lone_cond, 0)}, wrap_status=False)


def test_conditional_status_written_directly_by_a_test():
    rec = awd.run_walk_diff(_direct_status_scene, 40)
    assert rec.native_entries["stock_status_reads"] > 50, rec.native_entries
    assert _count(rec, "cond.GetStatus") == 0, rec.calls()
    statuses = _states(rec, "_status")
    assert ("int", US_DONE) in statuses          # the fold, and leaves ending
    assert _count(rec, "eval") > 0


def _s2_lifetime_scene(mp):
    """When the condition evaluation lets go of what it read: a custom
    GetStatus and an EvalFunc returning _Status objects (an int subclass, so
    never a memo key, and `int(status)` makes a new int). The refresh holds
    its `args` until it returns, _eval_conditional drops the EvalFunc's own
    result at `status = int(status)`, and _tick_conditional holds its args
    across the contained AI's tick."""
    ai = _ai()
    owner = awd.current()
    made = {"n": 0}

    def status(v, tag):
        s = _Status(v)
        s.owner, s.tag = owner, tag
        return s

    class Marked(ai.TGCondition):
        def GetStatus(self):
            made["n"] += 1
            return status(self._status, "c%d" % made["n"])

    ship = _ship()
    m1, m2 = Marked(), Marked()
    m1.SetStatus(1)
    m2.SetStatus(1)

    def Eval(a, b):
        made["n"] += 1
        return status(US_ACTIVE if (a and b) else US_DORMANT,
                      "e%d" % made["n"])

    root = _plist(ship, "Root",
                  (1, _gated(ship, "Marked", [m1, m2], Eval,
                             _leaf(ship, "MarkedLeaf"))),
                  (2, _gated(ship, "NoEval", [Marked()], None,
                             _leaf(ship, "NoEvalLeaf"))))
    _install(ship, root)
    return _s2_scene_of(mp, [ship], {3: lambda: m2.SetStatus(0)},
                        wrap_status=False)


def test_conditional_locals_are_released_where_python_releases_them():
    rec = awd.run_walk_diff(_s2_lifetime_scene, 6)
    marks = [e for e in rec.log() if e[0] == "mark"]
    assert len(marks) > 20, marks
    tick0 = rec.ticks[0][0]
    names = [e[:2] for e in tick0]
    # The leaf's Update runs inside _tick_conditional, whose args (c3, c4)
    # outlive it; the refresh's args (c1, c2) die before the dispatch.
    upd = names.index(("call", "script.Update"))
    assert tick0.index(("mark", "del status", "c1")) < upd, tick0
    assert tick0.index(("mark", "del status", "c4")) > upd, tick0


def test_harness_catches_a_native_side_that_runs_the_python_s2():
    def build(mp):
        ship = _ship()
        cond = _cond(1)
        _install(ship, _plist(ship, "Root", (1, _gated(
            ship, "G", [cond], lambda b: US_ACTIVE, _leaf(ship, "L")))))
        drv = _driver()
        mp.setattr(drv, "_aitree_refresh_conditional",
                   lambda ai, g: oracle.clone(
                       "_refresh_conditional_status_python")(ai))
        return awd.synthetic_scene(mp, [ship])
    with pytest.raises(AssertionError,
                       match="ran the Python condition evaluation"):
        awd.run_walk_diff(build, 5)


# ── the walk (Task 4: S4 native) ─────────────────────────────────────────────
#
# From Task 4 the native side walks natively: tick_ai, _dispatch_ai and every
# stock _tick_* handler (aitree_tick). The harness proves the native side ran
# the native walk and never the Python body (_tick_ai_python). The scenes
# below pin each Review Focus item of the plan on a tree built for it.

class ScriptedLeaf(Leaf):
    """A PlainAI script whose Update returns `results[n % len]` and marks
    whether its node held focus while it ran; with focus hooks."""

    def __init__(self, ai, results, owner, interval=0.0, on_update=None):
        super().__init__(ai, interval=interval, on_update=on_update)
        self.results = list(results)
        self.owner = owner

    def Update(self):
        self.n += 1
        awd.mark(self.owner, "focus in Update", self.pCodeAI.GetName(),
                 self.pCodeAI.HasFocus())
        if self.on_update is not None:
            self.on_update(self.n)
        return self.results[(self.n - 1) % len(self.results)]

    def GotFocus(self):
        return None

    def LostFocus(self):
        return None


class ScriptedPre(Pre):
    """A preprocessor whose PreUpdate returns `results[n % len]` (a PS_*, or
    anything else), marking whether its node held focus; with focus hooks."""

    def __init__(self, ai, results, owner, interval=0.0, on_update=None):
        super().__init__(ai, interval=interval, on_update=on_update)
        self.results = list(results)
        self.owner = owner

    def PreUpdate(self, dEndTime):
        self.n += 1
        awd.mark(self.owner, "focus in PreUpdate", self.pCodeAI.GetName(),
                 self.pCodeAI.HasFocus())
        if self.on_update is not None:
            self.on_update(self.n)
        return self.results[(self.n - 1) % len(self.results)]

    def GotFocus(self):
        return None

    def LostFocus(self):
        return None


def _sleaf(ship, name, results=(US_ACTIVE,), owner=None, **kw):
    node = _ai().PlainAI_Create(ship, name)
    node._script_instance = ScriptedLeaf(node, results, owner, **kw)
    return node


def _spre(ship, name, results, contained=None, owner=None, **kw):
    node = _ai().PreprocessingAI_Create(ship, name)
    node._preprocessing_instance = ScriptedPre(node, results, owner, **kw)
    node._preprocessing_method = "PreUpdate"
    if contained is not None:
        node.SetContainedAI(contained)
    return node


def _marks(rec, kind):
    return [e[2:] for e in rec.log() if e[0] == "mark" and e[1] == kind]


def _rollback_scene(mp):
    """Review Focus 3 and the priority list's rules.

    A: a dormant preprocessing child, probed whenever it is due (its own
    cadence, or a ForceUpdate from the fallback), rejected while it reports
    SKIP_DORMANT and accepted when it reports NORMAL: a rejected probe's
    focus records and queued GotFocus roll back, though its script saw
    HasFocus() == 1 during its own PreUpdate. B: an active child whose own
    Update turns it DORMANT, then (after a Reset) DONE: rolled back, and the
    list still stops at it that tick. C: every child DONE, so the list is
    DONE. D: a dormant ConditionalAI and a dormant PlainAI child are skipped
    without a dispatch."""
    owner = awd.current()
    holder = {}
    a = _ship("A")
    probe = _spre(a, "AProbe", [US_DORMANT] * 3 + [0] * 4 + [US_DORMANT] * 2,
                  _sleaf(a, "AInner", owner=owner, interval=0.02),
                  owner=owner, interval=0.1)

    def fallback_hook(n):
        if n % 7 == 0:
            holder["probe"].ForceUpdate()
    holder["probe"] = probe
    _install(a, _plist(a, "ARoot", (1, probe),
                       (2, _sleaf(a, "AFallback", owner=owner, interval=0.03,
                                  on_update=fallback_hook))))

    b = _ship("B")

    def b2_hook(n):
        if n in (4, 12):
            holder["b1"].Reset()
    b1 = _sleaf(b, "B1", [US_ACTIVE, US_ACTIVE, US_DORMANT, US_ACTIVE,
                          US_DONE], owner=owner, interval=0.02)
    holder["b1"] = b1
    _install(b, _plist(b, "BRoot", (1, b1),
                       (2, _sleaf(b, "B2", owner=owner, interval=0.02,
                                  on_update=b2_hook))))

    c = _ship("C")
    _install(c, _plist(c, "CRoot", (1, _leaf(c, "C1", done_after=2)),
                       (2, _leaf(c, "C2", done_after=3))))

    d = _ship("D")
    gate = _ai().ConditionalAI_Create(d, "DGate")
    gate._status = US_DORMANT
    sleeper = _leaf(d, "DSleeper")
    sleeper._status = US_DORMANT
    _install(d, _plist(d, "DRoot", (1, gate), (2, sleeper),
                       (3, _sleaf(d, "DLeaf", owner=owner, interval=0.05))))
    return _scene_of(mp, [a, b, c, d])


def test_priority_child_rollback_and_the_priority_rules():
    rec = awd.run_walk_diff(_rollback_scene, 150)
    pre = _marks(rec, "focus in PreUpdate")
    assert ("AProbe", 1) in pre and ("AProbe", 0) not in pre, pre
    assert _count(rec, "script.PreUpdate") >= 8, rec.calls()
    assert _count(rec, "script.GotFocus") >= 3, rec.calls()
    assert _count(rec, "script.LostFocus") >= 2, rec.calls()
    assert _count(rec, "node.ForceUpdate") >= 2, rec.calls()
    assert _count(rec, "node.Reset") == 2
    assert _count(rec, "ship.ClearAI") == 1           # C's list ends DONE
    statuses = {s for s in _states(rec, "_status")}
    assert ("int", US_DORMANT) in statuses and ("int", US_DONE) in statuses


def _bypass_scene(mp):
    """The non-interruptable bypass: while the contained node is ACTIVE and
    not interruptable, the preprocessor is not consulted at all (neither
    arm); the contained node's hook toggles SetInterruptable, and its DONE
    ends the bypass and folds into the preprocessor."""
    owner = awd.current()
    holder = {}
    s = _ship("S")

    def inner_hook(n):
        if n == 10:
            holder["inner"].SetInterruptable(1)
        if n == 25:
            holder["inner"].SetInterruptable(0)
    inner = _sleaf(s, "Inner", [US_ACTIVE] * 40 + [US_DONE], owner=owner,
                   interval=0.02, on_update=inner_hook)
    inner.SetInterruptable(0)
    holder["inner"] = inner
    pre = _spre(s, "Pre", [0, 0, US_DORMANT, 0], inner, owner=owner,
                interval=0.05)
    _install(s, _plist(s, "Root", (1, pre),
                       (2, _sleaf(s, "Low", owner=owner, interval=0.04))))
    return _scene_of(mp, [s])


def test_the_non_interruptable_bypass():
    rec = awd.run_walk_diff(_bypass_scene, 160)
    assert _count(rec, "node.IsInterruptable") >= 20, rec.calls()
    assert _count(rec, "script.PreUpdate") >= 3, rec.calls()
    updates = [m for m in _marks(rec, "focus in Update") if m[0] == "Inner"]
    assert len(updates) >= 30, updates


_PS_VALUES = (0, 1, 2, 3, 4, None, 7, -1, 1.0, True, "x")


def _ps_scene(mp):
    """Every PS_* value (and some that are none of them) from a preprocessor,
    in the due arm and, from `_last_preprocess_status`, the not-due arm: the
    stored value is the raw result (not int()'d), PS_NORMAL replaces None."""
    owner = awd.current()
    ships = []
    for k, value in enumerate(_PS_VALUES):
        s = _ship("PS%d" % k)
        pre = _spre(s, "Pre%d" % k, [0, value, value, 0], _sleaf(
            s, "Inner%d" % k, owner=owner, interval=0.02), owner=owner,
            interval=0.05)
        _install(s, _plist(s, "Root%d" % k, (1, pre),
                           (2, _sleaf(s, "Low%d" % k, owner=owner,
                                      interval=0.03))))
        ships.append(s)
    return _scene_of(mp, ships)


def test_ps_status_mapping_in_both_arms():
    rec = awd.run_walk_diff(_ps_scene, 90)
    seen = set(_states(rec, "_last_preprocess_status"))
    for v in (("int", 1), ("int", 2), ("int", 3), ("int", 7), ("f", "0x1.0000000000000p+0")):
        assert v in seen, (v, seen)
    assert True in seen and "x" in seen, seen
    assert _count(rec, "ship.ClearAI") == 0


def _retain_scene(mp):
    """PS_SKIP_ACTIVE: the suppressed subtree keeps its focus (no LostFocus
    on the way in, no second GotFocus on the way out), found through a
    PriorityList's (priority, node) tuples, a Sequence's plain list and a
    preprocessor's contained node; a node without focus is not re-recorded."""
    owner = awd.current()
    s = _ship("R")
    deep = _sleaf(s, "Deep", owner=owner, interval=0.02)
    inner_pre = _spre(s, "InnerPre", [0], deep, owner=owner, interval=0.04)
    seq = _ai().SequenceAI_Create(s, "Seq")
    seq.SetLoopCount(-1)
    seq.AddAI(_sleaf(s, "SeqLeaf", owner=owner, interval=0.03))
    inner = _plist(s, "Inner", (1, inner_pre), (2, seq))
    top = _spre(s, "Top", [0] * 3 + [1] * 5 + [0] * 2 + [1] * 2, inner,
                owner=owner, interval=0.05)
    _install(s, top)
    other = _ship("R2")
    lone = _spre(other, "Lone", [1, 1, 0], None, owner=owner, interval=0.05)
    _install(other, lone)
    return _scene_of(mp, [s, other])


def test_skip_active_retains_the_subtree_focus():
    rec = awd.run_walk_diff(_retain_scene, 150)
    assert ("int", 1) in set(_states(rec, "_last_preprocess_status"))
    assert _count(rec, "script.GotFocus") >= 2, rec.calls()
    assert _count(rec, "script.LostFocus") == 0, rec.calls()


def _sequence_live_scene(mp):
    """A sequence takes `n = len(_ais)` once per tick and reads `_ais[idx]`
    live: an EvalFunc (reached by the scan's refresh) appends a child (not
    reached before the wrap that tick), removes one (the list shifts under
    the scan), and finally removes two at once so `_ais[idx]` raises
    IndexError, which escapes."""
    s = _ship("Q")
    seq = _ai().SequenceAI_Create(s, "Seq")
    seq.SetLoopCount(-1)
    seq.SetSkipDormant(1)
    holder = {"k": 0}
    first = _leaf(s, "First", done_after=1)
    late = _leaf(s, "Late", done_after=1)
    extra = _leaf(s, "Extra", done_after=1)

    def eval_fn(bOn):
        holder["k"] += 1
        k = holder["k"]
        if k == 3:
            seq.AddAI(late)
        if k == 6:
            seq.RemoveAI(first)
        if k == 9:
            seq.AddAI(extra)
        if k == 12:
            seq.RemoveAI(late)
            seq.RemoveAI(extra)
        return US_ACTIVE if k % 4 == 0 else US_DORMANT
    gate = _ai().ConditionalAI_Create(s, "Gate")
    gate.AddCondition(_cond(1))
    gate.SetEvaluationFunction(eval_fn)
    gate.SetContainedAI(_leaf(s, "Gated", done_after=1))
    for child in (first, gate, _leaf(s, "Last", done_after=1)):
        seq.AddAI(child)
    _install(s, seq)
    return _scene_of(mp, [s])


def test_sequence_takes_n_once_and_reads_its_list_live():
    rec = awd.run_walk_diff(_sequence_live_scene, 60)
    sizes = {len(st) - 1 for st in _states(rec, "_ais") if st != awd._ABSENT}
    assert {3, 4} <= sizes, sizes
    assert _count(rec, "eval") >= 12, rec.calls()


def _ooa_scene(mp):
    """The one-slot out-of-action cache: X's preprocessor walks Y's tree mid-walk (a
    nested, non-root tick_ai), which moves the slot to Y, so X's next node
    re-asks; a hook writes `_ooa_cache[0] = None` as a test does; X dies at
    tick 40. Every answer is a probe int whose release is marked: the
    `_dead` local keeps it while the handler runs."""
    drv = _driver()
    owner = awd.current()
    clock = {"i": 0}
    x, y = _ship("X"), _ship("Y")
    y_root = _plist(y, "YRoot", (1, _leaf(y, "YLeaf")))
    _install(y, y_root)

    def x_hook(n):
        if n % 3 == 0:
            drv.tick_ai(y_root, (clock["i"] + 1) / 60.0)
        if n % 5 == 0:
            drv._ooa_cache[0] = None

    import engine.appc.ship_death as sd

    def ooa(ship):
        v = _Status(1 if ship is x and clock["i"] >= 40 else 0)
        v.owner, v.tag = owner, "%s%d" % (ship.GetName(), clock["i"])
        return v
    mp.setattr(sd, "_out_of_action", ooa)
    # The hook runs in the preprocessor, so X's contained nodes are still
    # dispatched after the slot has moved (and re-ask).
    _install(x, _plist(x, "XRoot", (1, _pre(x, "XPre", _plist(
        x, "XInner", (1, _leaf(x, "XLeaf"))), on_update=x_hook))))

    def step(i):
        clock["i"] = i
        drv.tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, [x], step, extra_ships=[y])


def test_the_out_of_action_slot():
    rec = awd.run_walk_diff(_ooa_scene, 50)
    asked = [e[2] for e in rec.log() if e[:2] == ("call", "_out_of_action")]
    xs = asked.count(("obj", "ShipClass", "X"))
    assert xs > 50, Counter(asked)                       # re-asked after Y
    assert len(_marks(rec, "del status")) > 50
    assert _count(rec, "ship.ClearAI") == 1             # X died at tick 40


class _StampLeaf(Leaf):
    """Update returns a probe status and GetNextUpdateTime a probe interval,
    each marking its release."""

    def __init__(self, ai, owner, interval):
        super().__init__(ai, interval=interval)
        self.owner = owner

    def Update(self):
        self.n += 1
        st = _Status(US_ACTIVE)
        st.owner, st.tag = self.owner, "plain status %d" % self.n
        return st

    def GetNextUpdateTime(self):
        st = _Stamp(self.interval)
        st.owner, st.tag = self.owner, "plain next %d" % self.n
        return st


class _StampPre(Pre):
    def __init__(self, ai, owner, interval):
        super().__init__(ai, interval=interval)
        self.owner = owner

    def GetNextUpdateTime(self):
        st = _Stamp(self.interval)
        st.owner, st.tag = self.owner, "pre next %d" % self.n
        return st


def _walk_lifetime_scene(mp):
    """The walk's frame locals are released where Python releases them:
    _tick_plain's `status` and `next_update`, _tick_preprocessing's `nxt`,
    _dispatch_priority_child's `had_focus` (a probe written over the child's
    `_has_focus` before the tick) and _tick_sequence's `idx` (a probe
    written over `_current_index`)."""
    drv = _driver()
    owner = awd.current()
    s = _ship("L")
    leaf = _ai().PlainAI_Create(s, "StampLeaf")
    leaf._script_instance = _StampLeaf(leaf, owner, 0.02)
    seq = _ai().SequenceAI_Create(s, "Seq")
    seq.SetLoopCount(-1)
    seq.AddAI(leaf)
    pre = _ai().PreprocessingAI_Create(s, "StampPre")
    pre._preprocessing_instance = _StampPre(pre, owner, 0.03)
    pre._preprocessing_method = "PreUpdate"
    pre.SetContainedAI(seq)
    child = _leaf(s, "Second", interval=0.05)
    root = _plist(s, "Root", (1, pre), (2, child))
    _install(s, root)

    def step(i):
        # The walk overwrites a preprocessor's `_has_focus` with True, so
        # this probe is then held only by _dispatch_priority_child's
        # `had_focus` local, released when that function returns. The scene
        # keeps no reference to either probe.
        pre._has_focus = _probe(_Status(0), owner, "had_focus %d" % i)
        seq._current_index = _probe(_Status(0), owner, "idx %d" % i)
        drv.tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, [s], step)


def _probe(value, owner, tag):
    value.owner, value.tag = owner, tag
    return value


def test_walk_locals_are_released_where_python_releases_them():
    rec = awd.run_walk_diff(_walk_lifetime_scene, 12)
    tags = [m[0].split()[0] for m in _marks(rec, "del status")]
    tags += [m[0].split()[0] for m in _marks(rec, "del stamp")]
    for kind in ("plain", "pre", "had_focus", "idx"):
        assert kind in tags, (kind, tags)
    # had_focus outlives the preprocessor's own subtree: released after the
    # leaf's Update of that tick, not when the walk overwrote `_has_focus`.
    tick0 = rec.ticks[0][0]
    upd = next(k for k, e in enumerate(tick0)
               if e[:2] == ("call", "script.Update"))
    assert tick0.index(("mark", "del status", "had_focus 0")) > upd, tick0


# ── a driver function patched (Review Focus 5), one at a time ────────────────

def _sink_scene(patched=None, breakdown=False):
    """One tree per stock handler path: a priority list with a dormant
    preprocessing probe (rollback) over a gated sequence holding a random
    node; a builder; a SKIP_ACTIVE preprocessor; a condition-only gate. With
    `patched`, that ai_driver global is replaced by a pass-through that marks
    each call, so both walkers must call it where Python does."""
    def build(mp):
        drv = _driver()
        owner = awd.current()
        if breakdown:
            mp.setattr(drv, "_AI_BREAKDOWN", {})
        if patched is not None:
            orig = getattr(drv, patched)

            def through(*a, _orig=orig, _name=patched):
                awd.mark(owner, "patched", _name)
                return _orig(*a)
            mp.setattr(drv, patched, through)
        s1 = _ship("P")
        cond = _cond(1)
        rnd = _ai().RandomAI_Create(s1, "Rnd")
        for k in range(3):
            rnd.AddAI(_leaf(s1, "R%d" % k, done_after=2, interval=0.02))
        seq = _ai().SequenceAI_Create(s1, "Seq")
        seq.SetLoopCount(-1)
        seq.AddAI(_leaf(s1, "SeqHead", done_after=1))
        seq.AddAI(rnd)
        gated = _conditional(s1, "Gated", cond, seq)
        probe = _spre(s1, "Probe", [US_DORMANT, US_DORMANT, 0, 0],
                      _sleaf(s1, "ProbeInner", owner=owner, interval=0.02),
                      owner=owner, interval=0.05)
        _install(s1, _plist(s1, "P1Root", (1, probe), (2, gated)))

        s2 = _ship("B")
        mod = types.ModuleType("_awd_sink_builder")
        mod.BuilderCreate1 = lambda pShip: _leaf(pShip, "Built", interval=0.04)
        mp.setitem(sys.modules, mod.__name__, mod)
        builder = _ai().BuilderAI_Create(s2, "Builder", mod.__name__)
        builder.AddAIBlock("one", "BuilderCreate1")
        builder._preprocessing_instance = Pre(builder, interval=0.1)
        builder._preprocessing_method = "PreUpdate"
        _install(s2, builder)

        s3 = _ship("K")
        skip = _spre(s3, "Skip", [0, 1, 1, 0], _plist(s3, "SkipInner", (
            1, _sleaf(s3, "SkipLeaf", owner=owner, interval=0.03))),
            owner=owner, interval=0.04)
        # SelectTarget-shaped (a callable DamageEvent, a bound pCodeAI), so
        # _ensure_select_target_initialized is called; already initialised.
        skip._preprocessing_instance.DamageEvent = lambda pEvent: None
        skip._preprocessing_instance._dauntless_codeaiset_done = True
        _install(s3, _plist(s3, "KRoot", (1, skip)))

        s4 = _ship("N")
        bare = _ai().ConditionalAI_Create(s4, "Bare")
        bare.AddCondition(_cond(1))
        bare.SetContainedAI(_leaf(s4, "BareLeaf", interval=0.03))
        _install(s4, bare)
        return _scene_of(mp, [s1, s2, s3, s4], {
            30: lambda: cond.SetStatus(0), 45: lambda: cond.SetStatus(1)})
    return build


def test_every_stock_handler_runs_natively():
    rec = awd.run_walk_diff(_sink_scene(), 90)
    kinds = rec.native_entries["native_handlers"]
    assert len(kinds) == 7 and all(k > 0 for k in kinds), kinds
    assert _count(rec, "random.choice") >= 2 and _count(rec, "eval") > 0


_PATCHABLE = (
    "tick_ai", "_dispatch_ai", "_resolve_dispatch", "_tick_preprocessing",
    "_dispatch_priority_child", "_queue_got_focus", "_focus_instance_of",
    "_retain_subtree_focus", "_note_due", "_note_due_ret", "_run_script_step",
    "_refresh_conditional_status", "_condition_statuses", "_any_condition",
    "_eval_conditional", "_activate_builder", "_reconcile_focus",
    "_flush_pending_got_focus", "_reconcile_active", "_dispatch_lost_focus",
    "_ensure_select_target_initialized")


@pytest.mark.parametrize("name", _PATCHABLE)
def test_a_patched_driver_function_is_called_by_both_walkers(name):
    rec = awd.run_walk_diff(_sink_scene(name), 90)
    assert ("patched", name) in {e[1:3] for e in rec.log()
                                 if e[0] == "mark"}, name


def test_a_stock_walk_never_enters_a_forwarder():
    """A forwarder (ai_driver's `_tick_plain`, `_dispatch_ai`, ...) runs the
    native body through aitree_run, so a walk that fell back to calling one
    would pass every differential and silently give back SIG-208's gain. A
    stock walk must inline them all. Counted with sys.setprofile on the
    forwarders' code objects, so no module global is swapped (a swap would
    defeat the identity gate and make this vacuous)."""
    drv = _driver()
    names = [n for n, v in vars(drv).items()
             if isinstance(v, types.FunctionType)
             and v.__code__.co_names[:1] == ("_aitree_run",)] + [
        "tick_ai", "_refresh_conditional_status", "_condition_statuses",
        "_any_condition", "_eval_conditional"]
    codes = {getattr(drv, n).__code__: n for n in names}
    assert len(codes) == 21, sorted(codes.values())
    entered = Counter()

    def prof(frame, event, _arg):
        if event == "call" and frame.f_code in codes:
            entered[codes[frame.f_code]] += 1

    sys.setprofile(prof)
    try:
        rec = awd.run_side(_sink_scene(), 90, native=True)
    finally:
        sys.setprofile(None)
    handlers = rec.entries["native_handlers"]
    assert len(handlers) == 7 and all(k > 0 for k in handlers), handlers
    assert rec.entries["native_reconcile"][0] > 0, rec.entries
    assert not entered, dict(entered)


def test_the_ai_breakdown_path_dispatches_through_timed_dispatch():
    rec = awd.run_walk_diff(_sink_scene("_timed_dispatch", breakdown=True), 60)
    assert any(e[:3] == ("mark", "patched", "_timed_dispatch")
               for e in rec.log())


def test_harness_catches_a_native_side_that_runs_the_python_walk():
    def build(mp):
        ship = _ship()
        _install(ship, _plist(ship, "Root", (1, _leaf(ship, "Leaf"))))
        drv = _driver()
        mp.setattr(drv, "_aitree_tick",
                   lambda ai, t, g: oracle.clone("_tick_ai_python")(ai, t))
        return awd.synthetic_scene(mp, [ship])
    with pytest.raises(AssertionError, match="ran the Python walk"):
        awd.run_walk_diff(build, 5)


# ── focus and activation bookkeeping (Task 5: S3 native) ─────────────────────
#
# From Task 5 the root end of a native walk is native too: _reconcile_focus
# (with _dispatch_lost_focus), _flush_pending_got_focus and _reconcile_active.
# The harness proves the native side ran them natively. SetActive /
# SetInactive stay Python calls; the native side skips only a STOCK one with
# no instance shadow whose edge test says nothing changes, which a scene can
# reach only with wrap_node_activation=False (otherwise the harness's own
# instance wrappers shadow every node's, and must all be called).

def _node_ids(snap, ship_name):
    for key, row in snap["ships"].items():
        if "'%s')" % ship_name in key:
            return set(row["nodes"])
    raise KeyError(ship_name)


def _phase_positions(rec, tick, ship_name):
    """Positions, in tick `tick`'s call log, of ship `ship_name`'s LostFocus,
    GotFocus, node SetInactive and node SetActive calls."""
    log, snap = rec.ticks[tick]
    ids = {("int", i) for i in _node_ids(snap, ship_name)}
    out = {"script.LostFocus": [], "script.GotFocus": [],
           "node.SetInactive": [], "node.SetActive": []}
    for k, e in enumerate(log):
        if e[0] == "call" and e[1] in out and e[2] in ids:
            out[e[1]].append(k)
    return out


def _handover_scene(wrap_activation=True, latch=False):
    """Two branches of one priority list hand the path to each other: a
    gated preprocessing branch A (gate open at ticks 20-39 and 60+) over the
    always-ready branch B. Each handover is LostFocus of the leaving nodes,
    GotFocus of the arriving ones, SetInactive of the leaving nodes (B's gate
    conditions are deactivated through the ConditionalAI's own SetInactive),
    SetActive of the reached ones. A second ship's root keeps its own lists.

    `latch`: APre's GotFocus latches ALeaf (queued after it) by hand, so the
    flush must skip ALeaf's GotFocus at that arrival."""
    def build(mp):
        owner = awd.current()
        s = _ship("H")
        cond = _cond(0)
        a_leaf = _sleaf(s, "ALeaf", owner=owner, interval=0.02)
        a = _spre(s, "APre", [0], a_leaf, owner=owner, interval=0.05)
        gate = _conditional(s, "AGate", cond, a)
        b_cond = _cond(1)
        b_leaf = _sleaf(s, "BLeaf", owner=owner, interval=0.03)
        b = _conditional(s, "BGate", b_cond, _spre(
            s, "BPre", [0], b_leaf, owner=owner, interval=0.04))
        _install(s, _plist(s, "HRoot", (1, gate), (2, b)))
        if latch:
            def got_focus():
                awd.mark(owner, "APre GotFocus")
                a_leaf.__dict__["_got_focus_called"] = True
            a._preprocessing_instance.GotFocus = got_focus
            a_leaf._script_instance.GotFocus = lambda: awd.mark(
                owner, "ALeaf GotFocus")
        t = _ship("T")
        t_cond = _cond(1)
        _install(t, _plist(t, "TRoot", (1, _conditional(
            t, "TGate", t_cond, _sleaf(t, "TLeaf", owner=owner,
                                       interval=0.02))),
            (2, _sleaf(t, "TFallback", owner=owner, interval=0.05))))
        return _scene_of(mp, [s, t], {
            20: lambda: cond.SetStatus(1), 40: lambda: cond.SetStatus(0),
            50: lambda: t_cond.SetStatus(0), 60: lambda: cond.SetStatus(1),
            70: lambda: t_cond.SetStatus(1)},
            wrap_node_activation=wrap_activation)
    return build


def _handover_ticks(rec):
    return [t for t, (log, _s) in enumerate(rec.ticks)
            if any(e[:2] == ("call", "script.LostFocus") for e in log)
            and any(e[:2] == ("call", "script.GotFocus") for e in log)]


def test_the_root_end_runs_its_four_phases_natively_in_order():
    rec = awd.run_walk_diff(_handover_scene(), 90)
    assert all(rec.native_entries["native_reconcile"]), rec.native_entries
    checked = 0
    for t in _handover_ticks(rec):
        pos = _phase_positions(rec, t, "H")
        lost, got = pos["script.LostFocus"], pos["script.GotFocus"]
        off, on = pos["node.SetInactive"], pos["node.SetActive"]
        if not lost:
            continue                   # ship T's handover
        assert len(lost) >= 2 and len(got) >= 2 and off and on, (t, pos)
        assert max(lost) < min(got) and max(got) < min(off) \
            and max(off) < min(on), (t, pos)
        checked += 1
    assert checked >= 3, checked
    # B's gate condition was deactivated and re-activated by the edges
    calls = rec.calls()
    assert calls["cond.SetInactive"] >= 2 and calls["cond.SetActive"] >= 2


def test_a_got_focus_latched_before_the_flush_is_skipped():
    rec = awd.run_walk_diff(_handover_scene(latch=True), 90)
    assert len(_marks(rec, "APre GotFocus")) >= 2
    # ALeaf arrives with APre each time, queued after it; APre's GotFocus
    # latches it first, so the flush skips it
    assert not _marks(rec, "ALeaf GotFocus")
    assert rec.calls()["script.GotFocus"] >= 4


def test_stock_no_edge_activation_calls_are_skipped_natively():
    rec = awd.run_walk_diff(_handover_scene(wrap_activation=False), 90)
    calls = rec.calls()
    assert calls["node.SetActive"] == 0 and calls["node.SetInactive"] == 0
    assert calls["cond.SetInactive"] >= 2 and calls["cond.SetActive"] >= 2
    assert rec.native_entries["activation_skips"] > 50, rec.native_entries


def test_the_stock_activation_capture_checks_its_shape():
    """_STOCK_SET_ACTIVE / _STOCK_SET_INACTIVE are taken at import, each
    checked against the body the native skip relies on (a docstring is
    ignored); anything else falls back to (None, None): never skipped."""
    drv = _driver()
    AI = _ai().ArtificialIntelligence
    on, off = AI.__dict__["SetActive"], AI.__dict__["SetInactive"]
    assert drv._STOCK_SET_ACTIVE == (on, on.__code__)
    assert drv._STOCK_SET_INACTIVE == (off, off.__code__)
    code = on.__code__

    def louder(self):
        if self._is_active_in_tree:
            return 1
        self._is_active_in_tree = True
        self._on_activated()

    def plain(self):
        if self._is_active_in_tree:
            return
        self._is_active_in_tree = True
        self._on_activated()
    try:
        on.__code__ = louder.__code__
        assert drv._capture_stock(on, drv._stock_set_active_shape) == (
            None, None)
        on.__code__ = plain.__code__
        assert drv._capture_stock(on, drv._stock_set_active_shape) == (
            on, plain.__code__)
        assert drv._capture_stock(off, drv._stock_set_active_shape) == (
            None, None)
    finally:
        on.__code__ = code


def test_without_a_stock_capture_nothing_is_skipped():
    def build(mp):
        drv = _driver()
        mp.setattr(drv, "_STOCK_SET_ACTIVE", (None, None))
        mp.setattr(drv, "_STOCK_SET_INACTIVE", (None, None))
        return _handover_scene(wrap_activation=False)(mp)
    rec = awd.run_walk_diff(build, 60)
    assert rec.native_entries["activation_skips"] == 0, rec.native_entries
    assert rec.calls()["cond.SetActive"] >= 2


class _Truth:
    """An `_is_active_in_tree` value whose truth test marks."""

    def __init__(self, owner, value, tag):
        self.owner, self.value, self.tag = owner, value, tag

    def __bool__(self):
        awd.mark(self.owner, "truth", self.tag, self.value)
        return self.value


def _patched_activation_scene(mp):
    """SetActive / SetInactive that must be CALLED by the native side (the
    harness leaves every node's alone here): a subclass override, an instance
    shadow, a class-level patch (ticks 30-49), a reassigned __code__ (ticks
    60-69), a data descriptor for `_is_active_in_tree`, and a non-bool value
    whose truth test runs Python (SetActive with a truthy one, SetInactive
    with a falsy one)."""
    owner = awd.current()
    ai = _ai()
    AI = ai.ArtificialIntelligence

    class Overridden(ai.PlainAI):
        def SetActive(self):
            awd.mark(owner, "override SetActive", self.GetName())
            super().SetActive()

    class Described(ai.PlainAI):
        @property
        def _is_active_in_tree(self):
            awd.mark(owner, "descriptor read", self.GetName())
            return self.__dict__.get("_described", False)

        @_is_active_in_tree.setter
        def _is_active_in_tree(self, v):
            self.__dict__["_described"] = v

    s = _ship("P")
    steps = (US_ACTIVE, US_DONE)            # so the sequence moves along
    over = Overridden(s, "Over")
    over._script_instance = ScriptedLeaf(over, steps, owner, interval=0.02)
    shadow = _sleaf(s, "Shadow", steps, owner=owner, interval=0.03)

    def shadow_set_active():
        awd.mark(owner, "shadow SetActive")
        AI.SetActive(shadow)
    shadow.SetActive = shadow_set_active
    desc = Described(s, "Desc")
    desc._script_instance = ScriptedLeaf(desc, steps, owner, interval=0.04)
    truthy = _sleaf(s, "Truthy", steps, owner=owner, interval=0.02)
    falsy = _sleaf(_ship("G0"), "Falsy", owner=owner, interval=0.02)
    cond = _cond(1)
    seq = _ai().SequenceAI_Create(s, "Seq")
    seq.SetLoopCount(-1)
    for n in (over, shadow, desc, truthy):
        seq.AddAI(n)
    _install(s, _plist(s, "PRoot", (1, seq)))
    g = _ship("G")
    gated = _conditional(g, "Gated", cond, falsy)
    _install(g, _plist(g, "GRoot", (1, gated), (2, _sleaf(
        g, "GFallback", owner=owner, interval=0.03))))
    stock_set_active = AI.__dict__["SetActive"]
    stock_code = stock_set_active.__code__

    def swapped(self):                   # the stock body, plus a logged call
        self.ForceUpdate()
        if self._is_active_in_tree:
            return
        self._is_active_in_tree = True
        self._on_activated()

    def class_patch():
        def patched(self):
            awd.mark(owner, "class SetActive", self.GetName())
            return stock_set_active(self)
        mp.setattr(AI, "SetActive", patched)

    def falsy_leaves():
        falsy.__dict__["_is_active_in_tree"] = _Truth(owner, False, "falsy")
        cond.SetStatus(0)

    actions = {
        5: lambda: truthy.__dict__.__setitem__(
            "_is_active_in_tree", _Truth(owner, True, "truthy")),
        12: falsy_leaves,
        20: lambda: cond.SetStatus(1),
        30: class_patch,
        50: lambda: mp.setattr(AI, "SetActive", stock_set_active),
        60: lambda: mp.setattr(stock_set_active, "__code__",
                               swapped.__code__),
        70: lambda: mp.setattr(stock_set_active, "__code__", stock_code),
    }
    return _scene_of(mp, [s, g], actions, wrap_node_activation=False)


def test_a_set_active_that_is_not_the_stock_one_is_called():
    rec = awd.run_walk_diff(_patched_activation_scene, 90)
    over = _marks(rec, "override SetActive")
    shadow = _marks(rec, "shadow SetActive")
    # called on every reconciliation that reaches them, not only on edges
    assert len(over) >= 10 and len(shadow) >= 10, (len(over), len(shadow))
    assert len(_marks(rec, "descriptor read")) >= 10
    assert ("truthy", True) in _marks(rec, "truth")
    assert ("falsy", False) in _marks(rec, "truth")
    assert len(_marks(rec, "class SetActive")) >= 10
    assert rec.calls()["node.ForceUpdate"] >= 5      # the swapped __code__
    assert rec.native_entries["activation_skips"] > 0, rec.native_entries


def _raising_activate_scene(mp):
    """A ConditionalAI whose ConditionScripts' Activate / Deactivate raise:
    swallowed inside ConditionScript.SetActive / SetInactive (as today), so
    the reconciliation goes on to the next node."""
    owner = awd.current()
    ai = _ai()

    class Raising:
        def Activate(self):
            raise _Boom("Activate")

        def Deactivate(self):
            raise _Boom("Deactivate")

    s = _ship("R")
    conds = []
    for k in range(2):
        c = ai.ConditionScript()
        c._instance = Raising()
        c.SetStatus(1)
        conds.append(c)
    gate = _gated(s, "RGate", conds, lambda a, b: US_ACTIVE if a else
                  US_DORMANT, _sleaf(s, "RLeaf", owner=owner, interval=0.02))
    _install(s, _plist(s, "RRoot", (1, gate),
                       (2, _sleaf(s, "RFallback", owner=owner,
                                  interval=0.03))))
    return _scene_of(mp, [s], {
        10: lambda: conds[0].SetStatus(0), 20: lambda: conds[0].SetStatus(1),
        30: lambda: conds[0].SetStatus(0), 40: lambda: conds[0].SetStatus(1)})


def test_a_condition_activate_that_raises_is_swallowed():
    rec = awd.run_walk_diff(_raising_activate_scene, 50)
    log = rec.log()
    assert not [e for e in log if e[0] == "escaped"]
    raised = Counter(e[1] for e in log if e[0] == "raise")
    assert raised["cond.Activate"] >= 4 and raised["cond.Deactivate"] >= 4, \
        raised


def _nested_reconcile_scene(mp):
    """Hooks that start a nested ROOT walk from inside the root end: a
    condition's Activate (during _reconcile_active) walks another ship and,
    once, its own ship; GotFocus (during the flush) and LostFocus (during
    _reconcile_focus) each walk the own ship once. A nested root walk rebinds
    the module walk state and rewrites the root's own lists under the outer
    reconciliation."""
    drv = _driver()
    ai = _ai()
    clock = {"t": 1 / 60.0}
    once = set()
    other = _ship("Other")
    other_root = _plist(other, "OtherRoot",
                        (1, _leaf(other, "OtherLeaf", interval=0.0)))
    _install(other, other_root)
    s = _ship("Main")
    holder = {}

    def walk_own(tag):
        if tag not in once:
            once.add(tag)
            drv.tick_ai(holder["root"], clock["t"])

    class Hook:
        def Activate(self):
            drv.tick_ai(other_root, clock["t"])
            walk_own("activate")

        def Deactivate(self):
            drv.tick_ai(other_root, clock["t"])
    c = ai.ConditionScript()
    c._instance = Hook()
    c.SetStatus(1)
    owner = awd.current()
    leaf = _sleaf(s, "Leaf", owner=owner, interval=0.02)
    pre = _spre(s, "Pre", [0], leaf, owner=owner, interval=0.05)
    pre._preprocessing_instance.GotFocus = lambda: walk_own("got")
    pre._preprocessing_instance.LostFocus = lambda: walk_own("lost")
    gate = _gated(s, "Gate", [c], lambda a: US_ACTIVE if a else US_DORMANT,
                  pre)
    holder["root"] = _plist(s, "MainRoot", (1, gate),
                            (2, _sleaf(s, "Fallback", owner=owner,
                                       interval=0.03)))
    _install(s, holder["root"])

    def step(i):
        clock["t"] = (i + 1) / 60.0
        if i == 20:
            c.SetStatus(0)
        if i == 40:
            c.SetStatus(1)
        drv.tick_all_ai(clock["t"])
    return awd.synthetic_scene(mp, [s], step, extra_ships=[other])


def test_a_nested_root_walk_from_the_root_end():
    rec = awd.run_walk_diff(_nested_reconcile_scene, 60)
    calls = rec.calls()
    assert calls["cond.Activate"] >= 2 and calls["cond.Deactivate"] >= 1
    assert calls["script.GotFocus"] >= 1 and calls["script.LostFocus"] >= 1

    def nested_walks(hook, ship):
        depth, found = 0, 0
        for e in rec.log():
            if e[:2] == ("call", hook):
                depth += 1
            elif e[:2] in (("ret", hook), ("raise", hook)):
                depth -= 1
            elif (depth and e[:2] == ("call", "_out_of_action")
                    and e[2] == ("obj", "ShipClass", ship)):
                found += 1
        return found
    assert nested_walks("cond.Activate", "Other") >= 1
    assert nested_walks("cond.Activate", "Main") >= 1
    assert nested_walks("script.GotFocus", "Main") >= 1
    assert nested_walks("script.LostFocus", "Main") >= 1


def test_harness_catches_a_native_side_that_runs_the_python_reconciliation():
    def build(mp):
        ship = _ship()
        _install(ship, _plist(ship, "Root", (1, _leaf(ship, "Leaf"))))
        drv = _driver()
        for n in ("_reconcile_focus", "_flush_pending_got_focus",
                  "_reconcile_active"):
            orig = oracle.clone(n)
            mp.setattr(drv, n, lambda *a, _o=orig: _o(*a))
        return awd.synthetic_scene(mp, [ship])
    with pytest.raises(AssertionError,
                       match="never ran the native reconciliation"):
        awd.run_walk_diff(build, 5)


# ── the preprocessor arity cache (Task 4 review) ─────────────────────────────

class _BadSig:
    """A callable whose inspect.signature raises TypeError (a bad
    __signature__): the arity probe's `except (TypeError, ValueError)`."""
    __signature__ = "not a signature"

    def __init__(self, inst):
        self.inst = inst

    def __call__(self, *a):
        awd.mark(self.inst.owner, "arity", "Weird", len(a))
        return 0


class _Multi:
    def __init__(self, ai, owner):
        self.pCodeAI = ai
        self.owner = owner
        self.Weird = _BadSig(self)

    def One(self, dEndTime):
        awd.mark(self.owner, "arity", "One", 1)
        return 0

    def Zero(self):
        awd.mark(self.owner, "arity", "Zero", 0)
        return 0

    def GetNextUpdateTime(self):
        return 0.03


def _arity_scene(mp):
    """The arity cache's paths: a 1-arg method, a 0-arg one (a miss on the
    method name), a stale entry (the 0-arg method replaced by a 1-arg one on
    the same instance under the same name: the cached 0 is used, the call
    raises TypeError and is swallowed), a callable whose signature cannot be
    taken (assumed 0-arg), the stale method named again after another (a
    miss: re-probed, 1), and a new instance under the same method name whose
    method takes no argument (a miss on the instance alone: 0)."""
    owner = awd.current()
    s = _ship("A")
    pre = _ai().PreprocessingAI_Create(s, "Pre")
    inst = _Multi(pre, owner)
    pre._preprocessing_instance = inst
    pre._preprocessing_method = "One"
    pre.SetContainedAI(_leaf(s, "L", interval=0.02))
    _install(s, _plist(s, "Root", (1, pre)))

    def swap_zero():
        pre._preprocessing_method = "Zero"

    def stale():
        def zero_now_one(dEndTime):
            awd.mark(owner, "arity", "Stale", 1)
            return 0
        inst.Zero = zero_now_one

    def weird():
        pre._preprocessing_method = "Weird"

    def new_inst():
        pre._preprocessing_instance = _Multi(pre, owner)
    return _scene_of(mp, [s], {10: swap_zero, 20: stale, 30: weird,
                               35: swap_zero, 40: new_inst})


def test_the_preprocessor_arity_cache_paths():
    rec = awd.run_walk_diff(_arity_scene, 60)
    by_tick = [(t, e[2:]) for t, (log, _s) in enumerate(rec.ticks)
               for e in log if e[:2] == ("mark", "arity")]
    for lo, hi, want in ((0, 10, ("One", 1)), (10, 20, ("Zero", 0)),
                         (20, 30, None), (30, 35, ("Weird", 0)),
                         (35, 40, ("Stale", 1)), (40, 60, ("Zero", 0))):
        got = {m for t, m in by_tick if lo <= t < hi}
        assert got == ({want} if want else set()), (lo, hi, got)
    errors = rec.ticks[-1][1]["errors"]
    assert any(k[1] == "TypeError" for k in errors), errors


# ── engine glue raising out of the walk (Task 4 review) ──────────────────────

class _SelectLike(Pre):
    """A SelectTarget-shaped preprocessor: a callable DamageEvent and a bound
    pCodeAI, so _tick_preprocessing calls _ensure_select_target_initialized.
    Already initialised, so the real one returns at once."""

    def __init__(self, ai, **kw):
        super().__init__(ai, **kw)
        self._dauntless_codeaiset_done = True

    def DamageEvent(self, pEvent):
        return None


def _glue_escape_scene(mp):
    """_sync_fire_script_target_subsystem, _ensure_select_target_initialized
    and a condition's GetStatus each raise once: the exception escapes the
    walk (and the roster) at the point Python's does."""
    drv = _driver()
    counts = Counter()
    ships = []

    def flaky(name, nth, orig):
        def fn(*a):
            counts[name] += 1
            if counts[name] == nth:
                raise _Boom(name)
            return orig(*a)
        return fn
    mp.setattr(drv, "_sync_fire_script_target_subsystem",
               flaky("_sync_fire", 5, drv._sync_fire_script_target_subsystem))
    mp.setattr(drv, "_ensure_select_target_initialized",
               flaky("_ensure_select", 9,
                     drv._ensure_select_target_initialized))
    s1 = _ship("Sel")
    pre = _ai().PreprocessingAI_Create(s1, "SelPre")
    pre._preprocessing_instance = _SelectLike(pre, interval=0.05)
    pre._preprocessing_method = "PreUpdate"
    pre.SetContainedAI(_leaf(s1, "SelLeaf", interval=0.02))
    _install(s1, _plist(s1, "SelRoot", (1, pre)))
    ships.append(s1)

    s2 = _ship("Cond")

    class FlakyCond(_ai().TGCondition):
        def GetStatus(self):
            counts["GetStatus"] += 1
            if counts["GetStatus"] == 7:
                raise _Boom("GetStatus")
            return self._status
    c = FlakyCond()
    c.SetStatus(1)
    _install(s2, _plist(s2, "CondRoot", (1, _gated(
        s2, "CondGate", [c], lambda a: US_ACTIVE if a else US_DORMANT,
        _leaf(s2, "CondLeaf", interval=0.02)))))
    ships.append(s2)
    s3 = _ship("After")
    _install(s3, _plist(s3, "AfterRoot", (1, _leaf(s3, "AfterLeaf"))))
    ships.append(s3)
    return _scene_of(mp, ships)


@pytest.mark.parametrize("wrap_status", [True, False])
def test_engine_glue_and_get_status_raising_escape_the_walk(wrap_status):
    def build(mp):
        scene = _glue_escape_scene(mp)
        scene.wrap_condition_status = wrap_status
        return scene
    rec = awd.run_walk_diff(build, 40)
    escaped = sorted(e[2] for e in rec.log() if e[0] == "escaped")
    assert escaped == ["GetStatus", "_ensure_select", "_sync_fire"], escaped


# ── the real fights ──────────────────────────────────────────────────────────

@needs_native
def test_k1_gameloop_ai_trees():
    rec = awd.run_walk_diff(_k1_scene(), 600, warm_ticks=2, aba=True)
    calls = rec.calls()
    assert calls["script.Update"] > 100, calls
    assert calls["eval"] > 0 and calls["cond.GetStatus"] > 1000, calls
    assert calls["script.GotFocus"] > 0 and calls["node.SetActive"] > 0
    assert calls["_sync_fire_script_target_subsystem"] > 0
    assert calls["_ensure_select_target_initialized"] > 0


@needs_native
def test_k1_gameloop_ai_trees_with_direct_condition_reads():
    """The same fight with no GetStatus and no node SetActive / SetInactive
    wrapped: the SDK's ConditionScripts (stock TGCondition.GetStatus) are
    read directly by the native side and called by the Python side, and a
    stock no-edge SetActive / SetInactive is skipped natively and called by
    the Python side; compared through every EvalFunc's arguments, the
    conditions' own SetActive / SetInactive and the node states."""
    rec = awd.run_walk_diff(_k1_scene(wrap_status=False,
                                      wrap_activation=False), 150,
                            warm_ticks=2)
    calls = rec.calls()
    assert calls["eval"] > 0 and calls["cond.GetStatus"] == 0, calls
    assert calls["node.SetActive"] == 0 and calls["cond.SetActive"] > 0
    assert rec.native_entries["stock_status_reads"] > 1000, rec.native_entries
    assert rec.native_entries["activation_skips"] > 1000, rec.native_entries


@needs_native
def test_sdk_dumb_fire_trees():
    rec = awd.run_walk_diff(_k1_scene(dumb_fire=True), 300, warm_ticks=2,
                            aba=True)
    assert rec.calls()["script.Update"] > 100


# ── the harness fails when the sides differ ──────────────────────────────────

def _negative_scene(kind):
    def build(mp):
        ship = _ship()
        leaf = _leaf(ship, "Leaf", interval=0.05)
        root = _plist(ship, "Root", (1, leaf))
        _install(ship, root)
        drv = _driver()

        def step(i):
            if awd.is_native():
                if kind == "state" and i == 7:
                    leaf._status = US_DORMANT
                if kind == "log" and i == 9:
                    leaf.ForceUpdate()
            drv.tick_all_ai((i + 1) / 60.0)
            if awd.is_native() and kind == "stamp" and i == 11:
                ship.__dict__["_ai_next_walk_due"] += 1 / 120.0
        return awd.synthetic_scene(mp, [ship], step)
    return build


def test_harness_catches_a_node_status_mutated_in_the_second_run():
    with pytest.raises(AssertionError) as err:
        awd.run_walk_diff(_negative_scene("state"), 30)
    assert "tick 7" in str(err.value) and "_status" in str(err.value), err.value


def test_harness_catches_an_extra_call_in_the_second_run():
    with pytest.raises(AssertionError) as err:
        awd.run_walk_diff(_negative_scene("log"), 30)
    assert "tick 9" in str(err.value) and "ForceUpdate" in str(err.value), \
        err.value


def test_harness_catches_a_native_side_that_never_enters_the_native_walker():
    def build(mp):
        ship = _ship()
        _install(ship, _plist(ship, "Root", (1, _leaf(ship, "Leaf"))))

        def step(i):
            if not awd.is_native():                 # the native entry is skipped
                _driver().tick_all_ai((i + 1) / 60.0)
        return awd.synthetic_scene(mp, [ship], step)
    with pytest.raises(AssertionError, match="never entered the native walker"):
        awd.run_walk_diff(build, 5)


def test_harness_catches_a_native_side_that_runs_the_python_walker():
    def build(mp):
        ship = _ship()
        _install(ship, _plist(ship, "Root", (1, _leaf(ship, "Leaf"))))
        drv = _driver()

        def step(i):
            t = (i + 1) / 60.0
            if awd.is_native() and i > 0:
                oracle.clone("_tick_all_ai_python")(t)     # the oracle's roster
            else:
                drv.tick_all_ai(t)
        return awd.synthetic_scene(mp, [ship], step)
    with pytest.raises(AssertionError, match="ran the Python walker"):
        awd.run_walk_diff(build, 5)


def test_harness_catches_a_native_entry_that_never_starts_the_native_roster():
    def build(mp):
        ship = _ship()
        _install(ship, _plist(ship, "Root", (1, _leaf(ship, "Leaf"))))
        drv = _driver()
        # The entry point runs, but its roster is a Python stand-in.
        mp.setattr(drv, "_aitree_tick_all",
                   lambda t, g: drv.tick_ai(ship.GetAI(), t))
        return awd.synthetic_scene(mp, [ship])
    with pytest.raises(AssertionError, match="native roster never ran"):
        awd.run_walk_diff(build, 5)


def test_harness_catches_a_wrong_sleep_stamp():
    with pytest.raises(AssertionError) as err:
        awd.run_walk_diff(_negative_scene("stamp"), 30)
    assert "tick 11" in str(err.value) and "walk_due" in str(err.value), \
        err.value
