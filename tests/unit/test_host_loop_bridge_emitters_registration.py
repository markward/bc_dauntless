"""Host-loop wiring of the Bridge Emitters dev panel."""
import pytest

from engine.ui.panel_registry import PanelRegistry


@pytest.fixture
def dev_env():
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    original_entries = list(dev_mode._dev_pause_menu_entries)
    dev_mode._dev_pause_menu_entries.clear()
    try:
        yield _dauntless_host, dev_mode
    finally:
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_entries)
        _dauntless_host.developer_mode = original_dev


class _Cam:
    def compute_camera(self):
        return ((0, 0, 50), (0, 1, 50), (0, 0, 1), 0.7)


class _Ctl:
    bridge_instance = None


class _View:
    is_bridge = True


def test_registered_under_developer_mode(dev_env):
    h, dev_mode = dev_env
    h.developer_mode = True
    from engine import host_loop
    reg = PanelRegistry()
    panel = host_loop._register_bridge_emitters(reg, _Cam(), _Ctl(), _View())
    assert reg.find("bridge-emitters") is panel
    labels = [label for label, _ in dev_mode._dev_pause_menu_entries]
    assert "Bridge Emitters…" in labels


def test_not_registered_without_developer_mode(dev_env):
    h, dev_mode = dev_env
    h.developer_mode = False
    from engine import host_loop
    reg = PanelRegistry()
    panel = host_loop._register_bridge_emitters(reg, _Cam(), _Ctl(), _View())
    assert panel is host_loop._NULL_PICKER
    assert reg.find("bridge-emitters") is None
    assert dev_mode._dev_pause_menu_entries == []


def test_bridge_camera_pose_prefers_the_editor_and_skips_shake():
    from engine import host_loop

    class Editor:
        def camera_pose(self):
            return ((1, 2, 3), (1, 3, 3), (0, 0, 1), 0.5)

    shaken = []

    def shake(e, t, u):
        shaken.append(True)
        return e, t, u

    assert host_loop._bridge_camera_pose(Editor(), _Cam(), shake) == \
        ((1, 2, 3), (1, 3, 3), (0, 0, 1), 0.5)
    assert shaken == []


def test_bridge_camera_pose_falls_back_to_the_shaken_bridge_camera():
    from engine import host_loop

    def shake(e, t, u):
        return (e[0] + 1, e[1], e[2]), t, u

    eye, target, up, fov = host_loop._bridge_camera_pose(
        host_loop._NULL_PICKER, _Cam(), shake)
    assert eye == (1, 0, 50) and fov == 0.7
