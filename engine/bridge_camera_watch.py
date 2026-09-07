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
        self._hold = False

    def watch(self, character, snap=False, hold=True) -> None:
        """Frame `character`. snap=True (AT_..._NOW) jumps instead of easing.
        Supersedes any prior target.

        `hold` separates BC's two verbs, and it is a PRECEDENCE flag, not a
        lifetime one — both kinds persist until cleared:

          hold=True  (AT_WATCH_ME) — an active follow. BC always pairs it with
              AT_STOP_WATCHING_ME and releases it BEFORE raising a menu
              (E1M1.py:2344-2345), so it outranks an open crew menu.
          hold=False (AT_LOOK_AT_ME[_NOW]) — the resting aim. BC never releases
              one, because it expects whatever comes next to supersede it. It
              therefore sits BELOW an open crew menu: E1M1's crew intros leave
              AT_LOOK_AT_ME(Picard) standing across every following
              introduction, and ranking it above the menu held the camera on
              Picard's face instead of framing the station being introduced.
        """
        self._watched = character
        self._snap_pending = snap
        self._hold = bool(hold)

    def is_holding(self) -> bool:
        """True when the live target came from AT_WATCH_ME (outranks a menu)."""
        return self._watched is not None and self._hold

    def clear(self) -> None:
        """Stop framing (AT_STOP_WATCHING_ME)."""
        self._watched = None
        self._snap_pending = False
        self._hold = False

    def is_watching(self) -> bool:
        return self._watched is not None

    def watched_character(self):
        """The CharacterClass currently being watched (or None). Lets the host
        drive MenuEventHandler on a watch-first engagement, where no crew-menu
        or hail engagement has yet populated _last_engaged_char."""
        return self._watched

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
        self._hold = False


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
