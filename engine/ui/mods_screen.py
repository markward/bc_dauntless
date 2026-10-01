"""Orchestrate the pre-boot Mods screen (spec 2026-10-01 mod ships §1.2, §3).

run_mods_screen(run_panel) is called once from host_loop.run() after
Foundation plugins load. It never raises: any fault boots as "skip for now".
"""
from __future__ import annotations

from typing import Callable, Optional

from engine import dev_mode, mods, ship_catalog


def decide_mode(argv=None) -> Optional[str]:
    if ship_catalog.incomplete_ships():
        return "gate"
    if mods.mods_screen_requested(argv):
        return "home"
    return None


def _write_rows(rows) -> None:
    from engine.ship_catalog import gate_writer
    for row in rows:
        gate_writer.write_answers(row.mod, row.ship_id, row.attr, row.answers)
    ship_catalog.invalidate()


def _build_panel(mode: str, error: str = ""):
    from engine.ui.mods_screen_panel import ModsScreenPanel
    incomplete = ship_catalog.incomplete_ships() if mode == "gate" else []
    ids = {r.ship_id for r in incomplete}
    readonly = [r for r in ship_catalog.ships("mod") if r.ship_id not in ids]
    stock = {r.values["title"]: r.values for r in ship_catalog.ships("stock") if r.values.get("title")}
    return ModsScreenPanel(mode, incomplete, readonly,
                           species=[s.name for s in ship_catalog.species()],
                           stock_classes=stock, writer=_write_rows, error=error)


def run_mods_screen(run_panel: Callable, argv=None) -> str:
    try:
        mode = decide_mode(argv)
        if mode is None:
            return "boot"
        error = ""
        for attempt in (1, 2):
            panel = _build_panel(mode, error)
            run_panel(panel)
            outcome = panel.outcome
            if outcome in (None, "quit"):
                return "quit"
            if outcome == "play":
                return "boot"
            if outcome == "skip":
                ship_catalog.skip_for_session([r.ship_id for r in ship_catalog.incomplete_ships()])
                return "boot"
            # continue: written and re-run; re-check once.
            left = ship_catalog.incomplete_ships()
            if not left:
                return "boot"
            if attempt == 2:
                ship_catalog.skip_for_session([r.ship_id for r in left])
                return "boot"
            error = ("Some answers did not take effect: %s"
                     % "; ".join("%s: %s" % (r.ship_id, ", ".join(r.errors) or ", ".join(r.missing))
                                 for r in left))
        return "boot"
    except Exception as exc:  # noqa: BLE001 -- a gate bug must never stop boot
        dev_mode.log_swallowed("Mods screen", exc)
        try:
            ship_catalog.skip_for_session([r.ship_id for r in ship_catalog.incomplete_ships()])
        except Exception as exc2:  # noqa: BLE001
            dev_mode.log_swallowed("Mods screen skip", exc2)
        return "boot"
