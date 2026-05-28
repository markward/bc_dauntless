"""SDK widget factories for ShipDisplay + its sub-views.

The SDK creates two ShipDisplay widgets per bridge load
(LoadBridge.py runs Tactical/Interface/ShipDisplay.py:Create twice —
once for the player, once for the enemy/target). We hand out
ROLE_PLAYER on the first call, ROLE_TARGET on the second; the SDK's
construction order in TacticalControlWindow is stable, so this is
deterministic.

The active PanelRegistry is injected via set_panel_registry() at
host-loop startup, before any bridge load runs.

Spec: docs/superpowers/specs/2026-05-28-ship-display-panel-design.md
"""
from __future__ import annotations

from typing import Optional

from engine.ui.panel_registry import PanelRegistry
from engine.ui.ship_display_panel import (
    ShipDisplayPanel,
    ROLE_PLAYER,
    ROLE_TARGET,
    _ShieldsSubview,
    _DamageSubview,
    _HullGaugeSubview,
)


_create_count: int = 0
_registry: Optional[PanelRegistry] = None


def set_panel_registry(registry: PanelRegistry) -> None:
    """Called by host_loop right after PanelRegistry is constructed."""
    global _registry
    _registry = registry


def _active_registry() -> Optional[PanelRegistry]:
    return _registry


def _reset_create_count() -> None:
    """Called on bridge teardown so the next bridge load starts clean.

    Kept for backwards-compatibility with existing tests.
    Prefer _reset_for_bridge_teardown() for host-loop-facing calls,
    as that also clears the registry reference."""
    global _create_count
    _create_count = 0


def _reset_for_bridge_teardown() -> None:
    """Called on bridge teardown so the next bridge load starts clean.

    Clears BOTH the create-count and the active registry reference.
    The next bridge load must call set_panel_registry(new_registry)
    before any ShipDisplay_Create call — otherwise registration is
    silently skipped, which is the desired loud-failure mode for
    misordered initialisation."""
    global _create_count, _registry
    _create_count = 0
    _registry = None


def ShipDisplay_Create(*args, **kwargs) -> ShipDisplayPanel:
    global _create_count
    if _create_count >= 2:
        raise RuntimeError(
            "ShipDisplay_Create called more than twice per bridge load; "
            "expected exactly two (player + target). "
            "Call _reset_for_bridge_teardown() on bridge unload to reset."
        )
    role = ROLE_PLAYER if _create_count == 0 else ROLE_TARGET
    _create_count += 1
    panel = ShipDisplayPanel(role)
    if _registry is not None:
        _registry.register(panel)
    return panel


def ShipDisplay_Cast(obj):
    return obj if isinstance(obj, ShipDisplayPanel) else None


def ShieldsDisplay_Create(*args, **kwargs) -> _ShieldsSubview:
    return _ShieldsSubview(parent=None)


def DamageDisplay_Create(*args, **kwargs) -> _DamageSubview:
    return _DamageSubview(parent=None)


def STFillGauge_Create(*args, **kwargs) -> _HullGaugeSubview:
    return _HullGaugeSubview(parent=None)
