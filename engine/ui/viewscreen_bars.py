"""Viewscreen target readout: data builder (name + range/speed + affiliation).

A top-left two-line readout on the viewscreen target feed: an affiliation dot
and the target name, then "DST: <km> km  SPD: <kph> kph". Shares the reticle's
numbers (reticle_text.readout_values / identity_name) so the readout and the
exterior reticle can never disagree. Text is always white (native side).
See docs/superpowers/specs/2026-10-21-viewscreen-target-bars-design.md
"""
from __future__ import annotations

from engine.appc import camera_modes, target_menu
from engine.ui import reticle_text

AFFILIATION_RGB = {
    "ENEMY": (216, 43, 43),
    "FRIENDLY": (80, 112, 230),
    "NEUTRAL": (255, 255, 175),
    "UNKNOWN": (128, 128, 128),
}


def _current_mission():
    import App
    game = App.Game_GetCurrentGame()
    episode = game.GetCurrentEpisode() if game is not None else None
    return episode.GetCurrentMission() if episode is not None else None


def build_viewscreen_bars(player, target) -> dict:
    if target is None or not camera_modes._target_alive(target):
        return {"visible": False}
    placeholder = reticle_text.identity_name(target)
    if placeholder is not None:
        affiliation = "UNKNOWN"
        name = placeholder
    else:
        affiliation = target_menu.resolve_affiliation(target, _current_mission())
        if affiliation not in AFFILIATION_RGB:
            affiliation = "UNKNOWN"
        name = target.GetDisplayName()
    return {
        "visible": True,
        "name": name,
        "detail": "DST: %.2f km  SPD: %.0f kph"
                  % reticle_text.readout_values(target, player),
        "dot_rgb": AFFILIATION_RGB[affiliation],
    }
