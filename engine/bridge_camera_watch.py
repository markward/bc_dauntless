# engine/bridge_camera_watch.py
"""BridgeCameraWatchController — the AT_WATCH_ME / AT_LOOK_AT_ME camera-framing
target.

BC's AT_WATCH_ME / AT_STOP_WATCHING_ME / AT_LOOK_AT_ME(_NOW) do NOT turn the
character — they aim the first-person captain's-eye bridge camera AT the named
character ("watch ME" = the camera watches me). This controller holds the
currently-watched CharacterClass; the host resolves its head-centre each bridge
frame and feeds it to the bridge camera's look-at spring (above the crew-menu
zoom, below a baked cutscene camera path).
"""


class BridgeCameraWatchController:
    def __init__(self):
        self._watched = None
        self._snap_pending = False

    def watch(self, character, snap=False) -> None:
        """Frame `character` (AT_WATCH_ME / AT_LOOK_AT_ME). snap=True (AT_..._NOW)
        jumps the camera instead of easing. Supersedes any prior target."""
        self._watched = character
        if snap:
            self._snap_pending = True

    def clear(self) -> None:
        """Stop framing (AT_STOP_WATCHING_ME)."""
        self._watched = None
        self._snap_pending = False

    def is_watching(self) -> bool:
        return self._watched is not None

    def resolve_target_world(self, renderer):
        """World-space head-centre of the watched character, or None (nothing
        watched / not yet realized / no renderer)."""
        ch = self._watched
        if ch is None:
            return None
        iid = getattr(ch, "_render_instance", None)
        if iid is None:
            return None
        try:
            c = renderer.get_instance_head_center(iid)
        except Exception:
            return None
        if not c:
            return None
        return (c[0], c[1], c[2])

    def consume_snap(self) -> bool:
        """Return True once after a snap (AT_..._NOW) set; then reset."""
        s = self._snap_pending
        self._snap_pending = False
        return s

    def reset(self) -> None:
        self._watched = None
        self._snap_pending = False


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
