"""Viewscreen target bars: data builder (name + range/speed + affiliation).

Shares the reticle's readout code (reticle_text.readout_line / identity_name)
so the bars and the exterior reticle can never disagree.
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
TEXT_RGB_ON = {
    "ENEMY": (255, 255, 255),
    "FRIENDLY": (255, 255, 255),
    "NEUTRAL": (0, 0, 0),
    "UNKNOWN": (255, 255, 255),
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
        top = placeholder
    else:
        affiliation = target_menu.resolve_affiliation(target, _current_mission())
        if affiliation not in AFFILIATION_RGB:
            affiliation = "UNKNOWN"
        top = target.GetDisplayName()
    return {
        "visible": True,
        "top_text": top,
        "bottom_text": reticle_text.readout_line(target, player),
        "band_rgb": AFFILIATION_RGB[affiliation],
        "text_rgb": TEXT_RGB_ON[affiliation],
    }
