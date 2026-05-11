from engine.ui import bindings


def test_bindings_returns_active_dom(fake_dom):
    assert bindings.dom() is fake_dom


def test_create_panel_calls_into_dom(fake_dom):
    pid = bindings.create_panel("targets", "top-right", 20.0, 60.0)
    # FakeDom assigns sequential ids starting at 1
    assert pid > 0
    assert fake_dom.panel_root(pid) is not None
