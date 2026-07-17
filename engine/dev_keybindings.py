"""Dev-only keybinding handlers. Imported by engine.host_loop on startup.

Handlers needing per-frame state (player ship, session) are re-bound every
tick via register_for_frame(); pure-static handlers can be registered once
at module import time.
"""
from pathlib import Path

import engine.dev_mode as dev_mode

# SP1 skinned-mesh preview: instance id of the spawned test character, or None.
# Module-level (not closure state) because register_for_frame re-binds the
# handler every tick, so the toggle state must survive across re-binds.
_test_character_iid = None

# Real skinned character NIF shipped with BC. Confirmed present at
# game/data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.NIF. Absolutised the
# same way host_loop resolves ship/bridge NIFs (PROJECT_ROOT / "game" / rel).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEST_CHARACTER_NIF = str(
    _PROJECT_ROOT
    / "game"
    / "data"
    / "Models"
    / "Characters"
    / "Bodies"
    / "BodyMaleL"
    / "BodyMaleL.NIF"
)


def register_for_frame(_h, session, player) -> None:
    """Re-bind handlers that close over per-frame state. Called once per tick
    from the host loop before dev_mode.dispatch_dev_key().
    """
    # F10: debug shield-hit on the shield surface. Real BC weapons impact the
    # bubble at a surface point; firing at the ship center would put the hit
    # too far inside the bubble for the distance falloff to ever exceed zero
    # on the visible shell. Offset along the ship's forward axis by ~1.0 x
    # the ship's GetRadius() so the hit lands near the bubble surface.
    def _f10_shield_debug() -> None:
        if player is None or session is None:
            return
        iid = session.ship_instances.get(player)
        if iid is None:
            return
        from engine.shields import fire_debug_hit
        wp = player.GetWorldLocation()
        try:
            fwd = player.GetWorldRotation().GetCol(1)
            fx, fy, fz = float(fwd.x), float(fwd.y), float(fwd.z)
        except Exception:
            fx, fy, fz = 1.0, 0.0, 0.0
        offset = 1.0 * player.GetRadius()
        fire_debug_hit(
            _h,
            instance_id=iid,
            world_point=(wp.x + fx * offset, wp.y + fy * offset, wp.z + fz * offset),
        )

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F10, _f10_shield_debug, "Shield-hit debug (F10)"
    )

    # [ : drop every ship's shields to zero (and stop regen) so weapons hit
    # the hull directly. Testing aid for hull-damage VFX (scorch decals).
    def _drop_all_shields() -> None:
        if session is None:
            return
        for ship in list(session.ship_instances.keys()):
            shields = ship.GetShields() if hasattr(ship, "GetShields") else None
            if shields is None:
                continue
            n = int(getattr(shields, "NUM_SHIELDS", 6))
            for f in range(n):
                try:
                    shields.SetCurrentShields(f, 0.0)
                    shields.SetShieldChargePerSecond(f, 0.0)
                except Exception as _e:
                    dev_mode.log_swallowed("dev drop-shields per facet", _e)

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_LEFT_BRACKET, _drop_all_shields,
        "Drop all shields to zero (dev) — [",
    )

    # ] : destroy the player's current target via the REAL death path
    # (DestroySystem on the hull -> critical-flag trigger -> throes ->
    # explosion -> dark hulk -> target-list drop -> removal). Testing aid
    # for the ship death sequence.
    def _destroy_target() -> None:
        if player is None:
            return
        target = player.GetTarget() if hasattr(player, "GetTarget") else None
        if target is None or target is player:
            return
        hull = target.GetHull() if hasattr(target, "GetHull") else None
        if hull is None or not hasattr(target, "DestroySystem"):
            return
        target.DestroySystem(hull)

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_RIGHT_BRACKET, _destroy_target,
        "Destroy target ship (dev) — ]",
    )

    # F7: spawn/despawn a skinned test character (SP1 skinned-mesh preview).
    # First press loads BodyMaleL.NIF and spawns one instance framed in front of
    # the active camera, tagged for the active pass (bridge or space) — the host
    # computes the bounds-aware placement. A non-empty skeleton routes it through
    # the skinned draw path automatically. Second press despawns it. Production
    # builds never register this (dev-mode gated).
    def _toggle_test_character() -> None:
        global _test_character_iid
        import engine.renderer as renderer

        if _test_character_iid is not None:
            renderer.destroy_instance(_test_character_iid)
            _test_character_iid = None
            return

        # The host frames the character in front of the active camera and tags
        # the active pass (bridge or space) — no Python-side placement math.
        # Asset load can raise (missing/corrupt NIF). Keep a load failure from
        # bubbling out into the frame body — log and stay un-spawned.
        try:
            _test_character_iid = renderer.spawn_test_character(
                _TEST_CHARACTER_NIF
            )
        except Exception as exc:  # noqa: BLE001 - dev hook must not break the tick
            print("[dev] spawn_test_character failed:", exc)
            _test_character_iid = None

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F7, _toggle_test_character,
        "Spawn/despawn skinned test character (SP1) — F7",
    )

    # F9: quick-repair the player ship (stock BC's Caps+R debug binding,
    # ET_INPUT_DEBUG_QUICK_REPAIR -> TacticalInterfaceHandlers.RepairShip).
    # Live-verify lever for the repair feature: damage, watch the queue
    # fill + Brex speak, F9, watch it all clear.
    def _quick_repair() -> None:
        from engine.appc.subsystems import repair_ship_fully
        repair_ship_fully(player)

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F9, _quick_repair, "Quick-repair player ship (dev) — F9"
    )

    # F8: toggle the engine-hum audio-geometry console readout (Part 2 of the
    # exterior-audio-fidelity live-verification pass — see
    # engine.audio.hum_diagnostic's module docstring for what it prints and
    # why). Prints ~once/second while ON; completely silent while OFF.
    def _toggle_hum_diagnostic() -> None:
        from engine.audio import hum_diagnostic
        hum_diagnostic.toggle()

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F8, _toggle_hum_diagnostic,
        "Toggle engine-hum diagnostic readout (dev) — F8",
    )
