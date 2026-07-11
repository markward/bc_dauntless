"""Renders MissionLib pointer arrows as a CEF overlay layer (#pointer-arrows).
Arrow (x,y) are normalized TopWindow coords -> vw/vh. Direction 0-9 maps to a
CSS class the stylesheet rotates/points."""

from engine.appc.tg_ui.layout import norm_to_vhvw


def build_arrows_script(arrows):
    parts = []
    for a in arrows:
        css = norm_to_vhvw(a["x"], a["y"], a.get("w", 0.0), a.get("h", 0.0))
        parts.append(
            "<div class='arrow arrow--%s' style=\"left:%s;top:%s\"></div>"
            % (a.get("dir"), css["left"], css["top"])
        )
    html = "".join(parts).replace("\\", "\\\\").replace("'", "\\'")
    return (
        "(function(){var e=document.querySelector('#pointer-arrows');"
        "if(!e)return;e.innerHTML='%s';})();" % html
    )


class ArrowOverlayPusher:
    """Emits the arrow-overlay script only when the arrow set changes
    (dirty-flag), mirroring PositionPusher (engine/ui/sdk_panel_positions.py,
    Task 8)."""

    def __init__(self, cef_execute_javascript):
        self._exec = cef_execute_javascript
        self._last = None

    def push(self, arrows):
        key = tuple(
            (round(a["x"], 4), round(a["y"], 4),
             round(a.get("w", 0.0), 4), round(a.get("h", 0.0), 4),
             a.get("dir"))
            for a in arrows
        )
        if self._last == key:
            return
        self._last = key
        self._exec(build_arrows_script(arrows))
