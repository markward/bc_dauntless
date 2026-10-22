"""The autouse `_reset_leakable_engine_globals` (tests/conftest.py) clears
module state a test can leave behind. Each pair here is ORDERED: the first
test leaves state, the second (run after it, in file order) must not see it.
"""


def test_a_leaves_an_explosion_light_glowing():
    from engine.appc import explosion_lights
    explosion_lights.register_at((0.0, 0.0, 0.0), None, size_gu=1.0, life_s=5.0)
    assert explosion_lights._active


def test_b_the_explosion_light_did_not_leak():
    from engine.appc import explosion_lights
    assert explosion_lights._active == []
    assert explosion_lights._sequences == []


def test_c_quickbattle_spawn_provider_leaks():
    from engine.quickbattle import spawn
    spawn.set_provider(lambda: "leaked-plan")
    assert spawn.current_plan() == "leaked-plan"


def test_d_the_quickbattle_spawn_provider_did_not_leak():
    from engine.quickbattle import spawn
    assert spawn.current_plan() is None


def test_e_quickbattle_player_type_resolver_leaks():
    from engine import bridge_selection
    bridge_selection.set_player_type_resolver(lambda qb: "leaked-type")
    assert bridge_selection._player_type_resolver is not None


def test_f_the_quickbattle_player_type_resolver_did_not_leak():
    from engine import bridge_selection
    assert bridge_selection._player_type_resolver is None


class _Ship:
    pass


def test_g_a_warp_core_breach_leaves_armed_and_breached_ships():
    from engine.appc import warp_core_breach
    warp_core_breach.arm(_Ship())
    warp_core_breach._breached.add(_Ship())
    warp_core_breach._growing.append({"ship": _Ship(), "age": 0.0, "next": 0})
    assert warp_core_breach._armed and warp_core_breach._breached


def test_h_the_warp_core_breach_state_did_not_leak():
    from engine.appc import warp_core_breach
    assert warp_core_breach._armed == []
    assert warp_core_breach._breached == set()
    assert warp_core_breach._growing == []


def test_i_cached_structure_part_labels_leak():
    from engine.appc import hull_breakup
    hull_breakup._part_labels[77] = (1, {(0.0, 0.0, 0.0, 1.0): 0})


def test_j_the_structure_part_labels_did_not_leak():
    from engine.appc import hull_breakup
    assert hull_breakup._part_labels == {}


def test_k_quickbattle_late_arrivals_leak():
    from engine.quickbattle import late_arrivals
    from engine.quickbattle.scenario import SpawnOrder
    order = SpawnOrder("g", "e", "Galor", "Galor", "Galor", None, None, "enemy",
                       "fore", 100.0, 0.5, warp_in_s=60.0)
    late_arrivals._pending[1] = {"orders": [(1, order)], "timer": -1}
    late_arrivals._qb = object()
    late_arrivals.set_rng(None)
    assert late_arrivals.pending_enemy_count() == 1


def test_l_the_quickbattle_late_arrivals_did_not_leak():
    from engine.quickbattle import late_arrivals
    assert late_arrivals.pending_enemy_count() == 0
    assert late_arrivals._qb is None
    assert late_arrivals._rng is not None
