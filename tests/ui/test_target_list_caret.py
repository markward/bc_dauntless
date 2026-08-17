"""Guards the phantom-chevron fix in target_list.js.

A ship row with zero subsystem rows (a cloaked contact's fuzzy return, or
an inert object like an asteroid whose hull/shields/power are all
non-targetable — tests/integration/test_target_list_inert_objects.py
confirms asteroids really do render with subsystems == []) must not show
an expand caret: there is nothing to expand, and clicking one toggled to
nothing.

There is no JS execution harness in this repo (grep confirms — no
package.json, no node/js2py driver anywhere under tests/), so this
mirrors the existing convention (test_ship_property_viewer_action_row.py,
test_developer_options_lighting_tab.py) of asserting on the JS source
text. The Python payload shape (row["subsystems"] == []) is already
covered at the unit level; this test pins the markup-generation logic
that consumes it.
"""

JS = "native/assets/ui-cef/js/target_list.js"


def _source():
    return open(JS).read()


def test_caret_is_gated_on_row_having_subsystems():
    text = _source()
    # The caret markup is chosen by a hasSubsystems gate, not emitted
    # unconditionally for every row.
    assert "hasSubsystems" in text
    assert "row.subsystems.length > 0" in text


def test_empty_caret_carries_no_toggle_and_no_glyph():
    text = _source()
    # The "no subsystems" branch must be a bare, empty span: no onclick
    # (nothing to toggle) and no glyph entity (nothing implying children).
    assert 'target-list__caret target-list__caret--empty">' in text
    empty_span = '<span class="target-list__caret target-list__caret--empty"></span>'
    assert empty_span in text


def test_populated_caret_still_carries_toggle_and_glyph():
    text = _source()
    # The has-subsystems branch is untouched: still clickable, still
    # swaps the collapsed/expanded glyph.
    assert ("'<span class=\"target-list__caret\"'\n"
            "              + ' onclick=\"event.stopPropagation();' + toggleAttr + '\">' + caretGlyph + '</span>'"
            in text)


def test_caret_span_shares_base_class_so_width_is_reserved_either_way():
    """Both branches use the target-list__caret base class (CSS gives it a
    fixed 14px width + 8px right margin) so a childless row's name column
    stays aligned with rows that DO have a caret — losing the glyph must
    not shift layout."""
    text = _source()
    assert 'class="target-list__caret"' in text
    assert 'class="target-list__caret target-list__caret--empty"' in text
