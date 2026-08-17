"""Guards the phantom-chevron fix in target_list.js / target_list.css.

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
that consumes it, plus the CSS that gives the two branches their box.

⚠️ round-1 fix: the original `.target-list__caret` rule had NO `width` (it
was content/glyph-driven, shrink-to-fit) — a false "flex: 0 0 auto; width:
14px" constraint led the first pass here to add an empty span and a test
asserting only that both spans share a class NAME, which is vacuous: it
cannot fail even if the two states render at different widths, because it
never inspects a CSS declaration. `.target-list__caret` now carries an
explicit `width` (see target_list.css), and the tests below parse the real
declaration blocks so a regression that reintroduces a size difference, or
that lets the empty variant re-acquire a pointer cursor, actually fails.
"""
import re

JS = "native/assets/ui-cef/js/target_list.js"
CSS = "native/assets/ui-cef/css/target_list.css"


def _source(path):
    return open(path).read()


def _rule(css_text, selector):
    """Return the declaration block body for an exact-match CSS selector
    (e.g. ".target-list__caret"), or raise if it isn't found.

    Anchored so `.target-list__caret` does not also match
    `.target-list__caret--empty { ... }` — the modifier's extra characters
    between the class name and `{` make the immediate `\\s*\\{` fail for it.
    """
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css_text)
    assert m is not None, "selector %r not found in %s" % (selector, CSS)
    return m.group(1)


def _declared_properties(block):
    """{property: value} for a CSS declaration block, values whitespace-
    trimmed. Strips /* ... */ comments first — both rules under test carry
    explanatory block comments, and a naive split on ';' would otherwise
    fold comment prose into a bogus "property"."""
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    props = {}
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        props[name.strip()] = value.strip()
    return props


def test_caret_is_gated_on_row_having_subsystems():
    text = _source(JS)
    # The caret markup is chosen by a hasSubsystems gate, not emitted
    # unconditionally for every row.
    assert "hasSubsystems" in text
    assert "row.subsystems.length > 0" in text


def test_empty_caret_carries_no_toggle_and_no_glyph():
    text = _source(JS)
    # The "no subsystems" branch must be a bare, empty span: no onclick
    # (nothing to toggle) and no glyph entity (nothing implying children).
    assert 'target-list__caret target-list__caret--empty">' in text
    empty_span = '<span class="target-list__caret target-list__caret--empty"></span>'
    assert empty_span in text


def test_populated_caret_still_carries_toggle_and_glyph():
    text = _source(JS)
    # The has-subsystems branch is untouched: still clickable, still
    # swaps the collapsed/expanded glyph.
    assert ("'<span class=\"target-list__caret\"'\n"
            "              + ' onclick=\"event.stopPropagation();' + toggleAttr + '\">' + caretGlyph + '</span>'"
            in text)


def test_base_caret_rule_declares_an_explicit_width():
    """The box must be deterministic (a fixed `width`), not shrink-to-fit
    around the glyph — a shrink-to-fit box is exactly what collapsed when
    the glyph was dropped for childless rows in the first place."""
    css = _source(CSS)
    props = _declared_properties(_rule(css, ".target-list__caret"))
    assert "width" in props, (
        ".target-list__caret must declare an explicit width so an empty "
        "caret occupies the same box as a populated one")


def test_empty_caret_modifier_does_not_resize_the_box():
    """The modifier class must NOT redeclare width/margin/padding — if it
    did, the two states could once again diverge in footprint. This is the
    assertion the original (vacuous) test was missing: it inspects the real
    CSS declarations, so a future width/margin/padding override on the
    modifier fails this test instead of silently shifting the name column."""
    css = _source(CSS)
    base = _declared_properties(_rule(css, ".target-list__caret"))
    empty = _declared_properties(_rule(css, ".target-list__caret--empty"))
    for sizing_prop in ("width", "margin-right", "padding"):
        assert sizing_prop not in empty, (
            ".target-list__caret--empty must not override %r — doing so "
            "would resize it relative to the populated .target-list__caret "
            "box and reintroduce the misalignment" % sizing_prop)
    # Sanity: the base rule actually sets these, so "not overridden" means
    # "inherited from the base rule" rather than "never set anywhere".
    assert "width" in base and "margin-right" in base


def test_empty_caret_modifier_overrides_the_pointer_cursor():
    """A childless row's caret slot is inert — nothing to click, nothing to
    toggle — so it must not show a pointer cursor (the base rule's
    `cursor: pointer`, meant for the clickable toggle, must not leak
    through to the non-interactive empty state)."""
    css = _source(CSS)
    base = _declared_properties(_rule(css, ".target-list__caret"))
    empty = _declared_properties(_rule(css, ".target-list__caret--empty"))
    assert base.get("cursor") == "pointer"
    assert "cursor" in empty and empty["cursor"] != "pointer"


def test_empty_caret_class_is_actually_defined_in_css():
    """Guard against the modifier existing only as a JS-side marker string
    with no matching CSS rule at all (round-1 state: it selected nothing)."""
    css = _source(CSS)
    assert re.search(r"\.target-list__caret--empty\s*\{", css) is not None


def test_empty_caret_click_falls_through_to_the_row_handler():
    """Documents + pins the intentional side effect of dropping onclick from
    the empty caret: with no handler (and no stopPropagation) on the span,
    a click there bubbles to the row div's own onclick and selects the ship
    — same as clicking the name or bars. Cheap to check at the source-text
    layer: the row div's onclick is built from `targetAttr` and wraps the
    caret markup, and the empty span carries no onclick attribute at all."""
    text = _source(JS)
    empty_span = '<span class="target-list__caret target-list__caret--empty"></span>'
    assert 'onclick' not in empty_span
    # The row div that contains it is still the one holding the click
    # handler that sets the target.
    assert ("html += '<div class=\"target-list__row target-list__row--' "
            "+ aff + chosen + expandedCls + '\"'\n"
            "              +   ' onclick=\"' + targetAttr + '\">'"
            in text)
