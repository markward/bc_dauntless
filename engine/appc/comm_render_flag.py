"""Developer-mode flag for the unbuilt comm/remote-set render path.

MissionLib.ViewscreenOn sets a remote camera on the bridge viewscreen
(SetRemoteCam) to show a remote set (e.g. a starbase commander). The
viewscreen RTT currently renders the forward space view and ignores that
remote camera, so comm scenes do not appear. This flag loudly announces the
gap once per activation under developer mode; production (dev off) is a
silent no-op so the render path stays byte-identical.
"""
import logging

from engine import dev_mode

_log = logging.getLogger(__name__)

_BANNER = ("comm-set rendering requested (viewscreen remote maincamera) — "
           "NOT IMPLEMENTED; viewscreen shows forward view instead.")


class CommRenderFlag:
    def __init__(self):
        self._announced_for = None     # id of the remote cam last announced

    def notice(self, viewscreen_obj) -> bool:
        if not dev_mode.is_enabled():
            return False
        if viewscreen_obj is None:
            return False
        cam = (viewscreen_obj.GetRemoteCam()
               if viewscreen_obj.IsOn() else None)
        if cam is None:
            self._announced_for = None      # reset when off / no remote cam
            return False
        if id(cam) == self._announced_for:
            return False                     # same activation -> silent
        self._announced_for = id(cam)
        _log.warning("%s", _BANNER)
        return True
