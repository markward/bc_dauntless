from engine.ui import ship_property_viewer_panel as m


def test_cluster_height_includes_action_row():
    expected = (m.TOOLS_H_PT + m.TOOLS_GAP_PT + m.TRANSFORM_H_PT
                + m.TOOLS_GAP_PT + m.ACTION_H_PT)
    assert m.TOOLS_CLUSTER_H_PT == expected


def test_cursor_over_tools_covers_new_row():
    # A point in the top row of the 3-row cluster (bottom-right) is inside.
    fb_w, fb_h, dsf = 1600.0, 900.0, 1.0
    # y at the very top of the cluster (top action row), x within the buttons.
    y_top = fb_h - m.TOOLS_MARGIN_PT - m.TOOLS_CLUSTER_H_PT + 2
    x_in = fb_w - m.TOOLS_MARGIN_PT - m.TOOLS_W_PT / 2
    assert m.ShipPropertyViewerPanel._cursor_over_tools(x_in, y_top, dsf, fb_w, fb_h)


HTML = "native/assets/ui-cef/index.html"
JS = "native/assets/ui-cef/js/ship_property_viewer.js"


def test_html_has_action_buttons():
    text = open(HTML).read()
    assert 'id="spv-action-tools"' in text
    for bid in ("spv-action-undo", "spv-action-pipette", "spv-action-mirror"):
        assert 'id="%s"' % bid in text


def test_js_defines_action_handlers():
    text = open(JS).read()
    for fn in ("shipPropertyViewerUndo", "shipPropertyViewerPipette",
               "shipPropertyViewerMirror"):
        assert fn in text
    # Guard the exact dispatch strings, not just the handler names — a
    # button silently firing "mirror" instead of "mirror_element" (etc.)
    # would pass the name-only check above but be a real regression.
    for dispatch in ("ship-property-viewer/undo", "ship-property-viewer/pipette",
                      "ship-property-viewer/mirror_element"):
        assert dispatch in text
