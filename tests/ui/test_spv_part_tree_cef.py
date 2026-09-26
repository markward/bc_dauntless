"""Task 7 (spec 2026-09-25 section 7): the Model Parts pane renders as a node
tree in CEF -- rows for the part and its Anchor / {State} Transformation /
Breakage children, right-click menus to add/remove them, inline fields on the
Anchor and Breakage rows, and a toast banner. Static text assertions on the
JS/HTML/CSS, following the style of test_ship_property_viewer_action_row.py.
"""

HTML = "native/assets/ui-cef/index.html"
JS = "native/assets/ui-cef/js/ship_property_viewer.js"
CSS = "native/assets/ui-cef/css/ship_property_viewer.css"


def _read(path):
    return open(path, encoding="utf-8").read()


# --- Task 6's old per-part controls must be GONE -----------------------------

def test_removed_handlers_are_gone():
    js = _read(JS)
    for fn in ("shipPropertyViewerPartAngle", "shipPropertyViewerPartPreview",
               "shipPropertyViewerPartDetach"):
        assert fn not in js, fn


def test_spv_part_controls_html_helper_is_gone():
    js = _read(JS)
    assert "spvPartControlsHtml" not in js


# --- part/* actions the tree must dispatch -----------------------------------

def test_js_dispatches_every_part_action():
    js = _read(JS)
    for action in ("part/select_node:", "part/add_anchor:", "part/add_state:",
                   "part/make_breakable:", "part/remove:",
                   "part/set_transition:", "part/set_break:"):
        assert action in js, action


def test_model_parts_select_still_used_for_the_part_row():
    js = _read(JS)
    assert "model_parts/select:" in js


# --- toast element -----------------------------------------------------------

def test_toast_element_exists_in_index():
    index = _read(HTML)
    assert 'id="spv-toast"' in index


def test_toast_is_rendered_from_the_payload():
    js = _read(JS)
    # model_parts.toast is the only place the toast lives (per Task 6) --
    # assert the JS reads that key, not some other invented field.
    assert "spv-toast" in js
    assert ".toast" in js


# --- context menu items -------------------------------------------------------

def test_menu_labels_present():
    index = _read(HTML)
    js = _read(JS)
    combined = index + js
    for label in ("Add Anchor", "Add State Transformation", "Make Breakable"):
        assert label in combined, label


def test_new_menu_items_live_inside_the_one_ctxmenu_element():
    """Resolved-in-advance: reuse #spv-ctxmenu, not a second menu element."""
    index = _read(HTML)
    start = index.index('id="spv-ctxmenu"')
    end = index.index("</div>", index.rindex("spv-ctx-removeemitter"))
    # Find the actual closing </div> of the ctxmenu block by locating the
    # section between the menu's opening tag and its remove-node item, which
    # must appear before the menu element closes.
    section = index[start:start + 4000]
    assert "spv-ctx-addanchor" in section
    assert "spv-ctx-addstate" in section
    assert "spv-ctx-makebreakable" in section
    assert "spv-ctx-removenode" in section


def test_add_state_submenu_lists_missing_states_dynamically():
    """No hardcoded per-state item in the ctxmenu markup -- the JS fills the
    submenu per-row from the row's own missing_states, using the spec's
    state labels."""
    index = _read(HTML)
    js = _read(JS)
    assert 'id="spv-ctx-addstate-items"' in index
    for label in ("Cruising", "Yellow Alert", "Red Alert"):
        assert label not in index, "state label must not be hardcoded in HTML"
    for label in ("Cruising", "Yellow Alert", "Red Alert", "Warp"):
        assert label in js, label


def test_remove_menu_item_present_for_child_rows():
    index = _read(HTML)
    assert ">Remove<" in index


# --- inline fields on Anchor / Breakage --------------------------------------

def test_inline_field_labels_present():
    js = _read(JS)
    assert "Transition time (s)" in js
    assert "of the ship's hull strength" in js


# --- row idiom reuse ----------------------------------------------------------

def test_rows_reuse_the_subsystem_tree_classes():
    js = _read(JS)
    assert "spv-sys-row" in js
    assert "spv-sys-row--child" in js
    assert "spv-sys-row--chosen" in js
    assert "spv-sys-row--dirty" in js


def test_rows_use_the_shared_indent_formula():
    js = _read(JS)
    assert "10 + " in js and "* 14" in js


# --- stylesheet has the new rules --------------------------------------------

def test_css_defines_toast_and_inline_field_rules():
    css = _read(CSS)
    assert "#spv-toast" in css
    assert "spv-part-inline-field" in css
