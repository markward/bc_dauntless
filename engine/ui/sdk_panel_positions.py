"""Drives CEF panel position from SDK-resolved rects. Only panels the SDK
defines are listed here; Dauntless-invented panels stay CSS-positioned and are
never touched by this channel."""

from engine.appc.tg_ui.layout import norm_to_vhvw

SDK_POSITIONED_PANELS = {
    "officer-menu": "#crew-menu-host",
    # follow-on: "target-list": "#...", "ship-display": "#...", ...
}


def build_position_script(panel_id, rect):
    selector = SDK_POSITIONED_PANELS[panel_id]
    css = norm_to_vhvw(rect.left, rect.top, rect.width, rect.height)
    return (
        "(function(){var e=document.querySelector('%s');if(!e)return;"
        "e.style.position='fixed';e.style.left='%s';e.style.top='%s';"
        "e.style.width='%s';e.style.height='%s';})();"
        % (selector, css["left"], css["top"], css["width"], css["height"])
    )


class PositionPusher:
    """Emits a position script only when a panel's rect changes (dirty-flag)."""

    def __init__(self, cef_execute_javascript):
        self._exec = cef_execute_javascript
        self._last = {}

    def push(self, rects):
        for panel_id, rect in rects.items():
            key = (round(rect.left, 4), round(rect.top, 4),
                   round(rect.width, 4), round(rect.height, 4))
            if self._last.get(panel_id) == key:
                continue
            self._last[panel_id] = key
            self._exec(build_position_script(panel_id, rect))
