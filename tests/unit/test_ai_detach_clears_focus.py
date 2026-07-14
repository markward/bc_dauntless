"""Detaching an AI tree (ClearAI / SetAI-over-an-old-tree) must tear down the
FOCUS lifecycle, not just the ACTIVATION lifecycle.

`_reconcile_focus` tracks the focused set PER ROOT (`root_ai._focused_preprocessors`),
exactly as `_reconcile_active` tracks the active set per root. So a node's
`_has_focus` / `_got_focus_called` latches can only be cleared by the same root
that set them — and a detached root never ticks again. Three consequences, all
real:

1. AI/PlainAI/Warp.LostFocus RE-ENABLES THE COLLISIONS IT DISABLED. Detach a
   warping ship's AI and, without this teardown, the ship stays permanently
   non-collidable.
2. The Fleet-Command override idiom (Bridge/HelmMenuHandlers.py:2310-2326:
   AddAI(old, 2) -> ClearAI(0, old) -> SetAI(override)) re-parents the SAME old
   subtree under a new root. When the override finishes and the priority list
   falls back to it, SetActive() re-fires (the activation fix) but GotFocus()
   could not — `_got_focus_called` was still latched from the old root. A node
   re-activated but never re-focused is self-contradictory: e.g.
   AI/PlainAI/StarbaseAttack.GotFocus (which starts firing) would never run.
3. HasFocus() stayed 1 on detached nodes, so ArtificialIntelligence.GetFocusAIs()
   reported nodes that are not on any focus path.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PriorityListAI_Create,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
)


class _Leaf:
    """Stand-in for a PlainAI script: records the focus lifecycle."""

    def __init__(self, status=ArtificialIntelligence.US_ACTIVE):
        self.got = 0
        self.lost = 0
        self._status = status

    def GotFocus(self):
        self.got += 1

    def LostFocus(self):
        self.lost += 1

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        return self._status


def _ship(name="Ours"):
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    ship._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ship._impulse_engine_subsystem.SetMaxSpeed(120.0)
    ship._warp_engine_subsystem = WarpEngineSubsystem("WES")
    pSet.AddObjectToSet(ship, name)
    return ship, pSet


# --- (a) the real Warp.py leaf: LostFocus re-enables collisions --------------


def test_clear_ai_re_enables_collisions_a_warping_ship_had_disabled():
    """The headline payoff. AI/PlainAI/Warp.py:217 LostFocus:
        if self.bCollisionsDisabled:
            pShip.SetCollisionsOn(1)
    Detaching the tree without dispatching LostFocus leaves the ship
    permanently non-collidable."""
    ship, _pSet = _ship()

    root = PriorityListAI_Create(ship, "root")
    warp = PlainAI_Create(ship, "warp")
    warp.SetScriptModule("Warp")
    root.AddAI(warp, 0)
    ship.SetAI(root)

    tick_ai(root, 0.0)                       # warp leaf takes focus
    inst = warp.GetScriptInstance()
    assert warp.HasFocus() == 1

    # The script has begun a warp: it disabled the ship's collisions.
    inst.bCollisionsDisabled = 1
    ship.SetCollisionsOn(0)
    assert ship.CanCollide() == 0

    ship.ClearAI()

    assert inst.bCollisionsDisabled == 0, "Warp.LostFocus must have run"
    assert ship.CanCollide() == 1, (
        "a detached warp AI must re-enable the collisions it disabled")


# --- (b) no node of a detached tree keeps focus ------------------------------


def test_a_detached_tree_holds_no_focus_and_dispatched_lost_focus():
    ship, _pSet = _ship()

    root = PriorityListAI_Create(ship, "root")
    leaf_ai = PlainAI_Create(ship, "leaf")
    leaf = _Leaf()
    leaf_ai._script_instance = leaf
    root.AddAI(leaf_ai, 0)
    ship.SetAI(root)

    tick_ai(root, 0.0)
    assert leaf.got == 1
    assert leaf_ai.HasFocus() == 1

    ship.ClearAI()

    assert leaf.lost == 1, "LostFocus must be dispatched on detach"
    assert leaf_ai.HasFocus() == 0
    assert root.HasFocus() == 0
    assert leaf_ai.__dict__.get("_got_focus_called", False) is False, (
        "the GotFocus latch must be cleared, else GotFocus can never re-fire")
    assert list(getattr(root, "_focused_preprocessors", [])) == []
    assert list(getattr(root, "_active_nodes", [])) == []


def test_set_ai_over_an_old_tree_also_clears_focus():
    """SetAI's old-tree branch is the other detach point."""
    ship, _pSet = _ship()

    old_root = PriorityListAI_Create(ship, "old")
    leaf_ai = PlainAI_Create(ship, "leaf")
    leaf = _Leaf()
    leaf_ai._script_instance = leaf
    old_root.AddAI(leaf_ai, 0)
    ship.SetAI(old_root)
    tick_ai(old_root, 0.0)
    assert leaf_ai.HasFocus() == 1

    ship.SetAI(PriorityListAI_Create(ship, "new"))

    assert leaf.lost == 1
    assert leaf_ai.HasFocus() == 0


# --- (c) the Fleet-Command override: the old subtree is re-focused on fallback


def test_fleet_command_override_re_focuses_the_old_subtree_on_fallback():
    """Bridge/HelmMenuHandlers.OverrideAIInternal (2310-2326):
        pOverrideAI.AddAI(pOldAI, 2)    # graft the SAME old tree, low priority
        pShip.ClearAI(0, pOldAI)        # detach it from the ship (no delete)
        pShip.SetAI(pOverrideAI)        # install the override root
    When the override finishes (US_DONE), the priority list falls back to the old
    subtree. SetActive() re-fires; GotFocus() must re-fire too."""
    ship, _pSet = _ship()

    old_root = PriorityListAI_Create(ship, "old")
    old_leaf_ai = PlainAI_Create(ship, "old_leaf")
    old_leaf = _Leaf()
    old_leaf_ai._script_instance = old_leaf
    old_root.AddAI(old_leaf_ai, 0)
    ship.SetAI(old_root)

    tick_ai(ship.GetAI(), 0.0)
    assert old_leaf.got == 1

    # --- the override sequence, in the SDK's exact order.
    override = PriorityListAI_Create(ship, "override")
    override_ai = PlainAI_Create(ship, "override_leaf")
    override_leaf = _Leaf()
    override_ai._script_instance = override_leaf
    override.AddAI(override_ai, 0)
    override.AddAI(old_root, 2)
    ship.ClearAI(0, old_root)
    ship.SetAI(override)

    assert old_leaf.lost == 1, "detaching the old tree must dispatch LostFocus"

    tick_ai(ship.GetAI(), 0.1)
    assert override_leaf.got == 1
    assert old_leaf.got == 1, "the old leaf is starved by the override"

    # The override finishes; the priority list falls back to the old subtree.
    override_leaf._status = ArtificialIntelligence.US_DONE
    tick_ai(ship.GetAI(), 0.2)   # override reports DONE
    tick_ai(ship.GetAI(), 0.3)   # old subtree runs again

    assert old_leaf.got == 2, (
        "the old subtree must be re-focused on fallback, not just re-activated")
    assert old_leaf_ai.HasFocus() == 1
    assert override_leaf.lost == 1, "the finished override loses focus"
