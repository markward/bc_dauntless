"""Identifier-centric UI attention: MissionLib.ShowPointerArrow/HidePointerArrows
override -> a highlight set keyed by widget id (engine/appc/tg_ui/widgets.ensure_widget_id).

See engine/ui/ui_attention.py and
docs/superpowers/specs/2026-07-12-identifier-centric-ui-attention-design.md.
"""
from engine.ui import ui_attention
from engine.appc.tg_ui.widgets import ensure_widget_id, TGPane


class _Widget(TGPane):
    def __init__(self, visible=True):
        super().__init__()
        self._vis = visible

    def IsCompletelyVisible(self):
        return 1 if self._vis else 0


def setup_function(_):
    ui_attention.hide_pointer_arrows()


def test_show_adds_widget_id():
    w = _Widget()
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    assert ensure_widget_id(w) in ui_attention.highlighted_ids()


def test_show_bails_on_none_and_invisible():
    ui_attention.show_pointer_arrow(None, None, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == set()
    hidden = _Widget(visible=False)
    ui_attention.show_pointer_arrow(None, hidden, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == set()


def test_hide_clears_all():
    a, b = _Widget(), _Widget()
    ui_attention.show_pointer_arrow(None, a, 0, 0.0, None)
    ui_attention.show_pointer_arrow(None, b, 0, 0.0, None)
    ui_attention.hide_pointer_arrows()
    assert ui_attention.highlighted_ids() == set()


def test_reissuing_same_set_is_idempotent():
    w = _Widget()
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    first = set(ui_attention.highlighted_ids())
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, None)
    assert ui_attention.highlighted_ids() == first


def test_show_records_color():
    w = _Widget()
    ui_attention.show_pointer_arrow(None, w, 0, 0.0, "gold")
    assert ui_attention.highlight_color(ensure_widget_id(w)) == "gold"


def test_install_overrides_missionlib():
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools import mission_harness
    mission_harness.setup_sdk()

    import MissionLib
    ui_attention.install()
    assert MissionLib.ShowPointerArrow is ui_attention.show_pointer_arrow
    assert MissionLib.HidePointerArrows is ui_attention.hide_pointer_arrows


def test_install_survives_reset_sdk_globals():
    """reset_sdk_globals() runs before every mission Initialize() call — the
    first mission load AND every in-process swap (engine/host_loop.py
    _init_mission / load_quickbattle / HostController._drain_pending_swap all
    call it first). MissionLib the module is never reloaded/re-imported on
    swap (confirmed by reading reset_sdk_globals — it only does `import
    MissionLib`, a cache hit, plus a couple of attribute writes), so in
    practice the override already survives. This test guards the case
    defensively: reset_sdk_globals() re-applies install() every time it
    runs, so even if something else clobbers the override mid-mission, the
    next swap repairs it."""
    import sys
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools import mission_harness
    mission_harness.setup_sdk()

    import MissionLib
    from engine.host_loop import reset_sdk_globals

    # Simulate the override having been lost/never installed.
    MissionLib.ShowPointerArrow = None
    MissionLib.HidePointerArrows = None

    reset_sdk_globals()

    assert MissionLib.ShowPointerArrow is ui_attention.show_pointer_arrow
    assert MissionLib.HidePointerArrows is ui_attention.hide_pointer_arrows
