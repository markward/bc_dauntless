"""The tree-walk differential harness proves itself (phase 6 AI part 4, Task 1).

Until the native walker lands both sides of ``run_walk_diff`` run the Python
walker, so every scene passes; what these tests pin is that the harness is
deterministic (two Python runs agree call for call and field for field), that
each scene reaches the driver paths it claims (asserted on the recorded call
log, not on the scene's intent), and that it fails when the sides differ.
"""
import gc
import sys
import types

import pytest

import App

from tests.helpers import ai_walk_diff as awd

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

needs_native = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k1_next"),
    reason="native K1 bindings not built")


def _k1_scene(dumb_fire=False):
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
        return awd.Scene(lambda: list(iter_ships()), step, wrap_roster=False)
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


def _scene_of(mp, ships, actions=None):
    """A synthetic scene: `actions[i]()` runs before tick i's walk."""
    actions = actions or {}

    def step(i):
        if i in actions:
            actions[i]()
        _driver().tick_all_ai((i + 1) / 60.0)
    return awd.synthetic_scene(mp, ships, step)


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
            if drv._native_walker:
                if kind == "state" and i == 7:
                    leaf._status = US_DORMANT
                if kind == "log" and i == 9:
                    leaf.ForceUpdate()
            drv.tick_all_ai((i + 1) / 60.0)
            if drv._native_walker and kind == "stamp" and i == 11:
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
            _driver()._native_walker = False        # the selector is bypassed
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
            if drv._native_walker and i > 0:
                drv._tick_all_ai_python(t)      # delegating, as Task 1 did
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
