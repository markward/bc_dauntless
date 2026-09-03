"""z-index containment across the CEF UI.

Three bugs this year had one shape: an element was given a z-index inside a
container that formed NO stacking context, so the value escaped into a scope
nobody had reasoned about and outranked something it should have sat under.

  * `.sdk-letterbox` at z-index 5 painted the cutscene bars OVER the XO menu
    mid-tutorial (see CLAUDE.md).
  * `.sm-label` at z-index 2 and `.sm-here-arrow` at 3 drew the system name
    and the you-are-here arrow straight THROUGH the open target popup, which
    paints at `auto` and therefore lost (fixed in 871cea75).

The rule that catches this is NOT "the element has some ancestor with a
z-index" — every one of these did; #star-map-panel sits at z-index 50. It is
that the element's NEAREST POSITIONED ancestor must itself create a stacking
context, so the value stays local to the layer it was reasoned about in.

This is a RATCHET, not a clean bill of health. The six escapes below are
pre-existing and currently benign — each cluster escapes to one shared
context where its relative order happens to be right. They are listed so a
SEVENTH cannot appear unnoticed, and so fixing one is a deliberate act (the
test then tells you to delete its line). Fixing them means giving the
container a z-index, which changes real stacking and wants its own live pass
— it is not free.
"""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}
_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>")


# Escapes that exist today. Each entry is "<element> in <container>", using the
# same naming the failure message prints, with the reason it is tolerated.
_KNOWN_ESCAPES = {
    # The map's own two layers. Both escape to #star-map-panel (z 50) and are
    # ordered correctly against each other there (labels 1 < targets 2), which
    # is what 871cea75 relies on. Containing them on #star-map-viewport would
    # be tidier but that element is the transparent hole the GL map shows
    # through, so it is not a change to make casually.
    "#star-map-labels in #star-map-viewport",
    "#star-map-targets in #star-map-viewport",

    # Ship-display silhouette stack: shields (1-4), silhouette (2) and the
    # damage overlay (5) are ordered against each other only.
    ".ship-display__silhouette in .ship-display__silhouette-stack",
    ".ship-display__damage-overlay in .ship-display__silhouette-stack",
    ".shield--top.ship-display__shield in .ship-display__silhouette-stack",
    ".shield--bottom.ship-display__shield in .ship-display__silhouette-stack",
    ".shield--front.ship-display__shield in .ship-display__silhouette-stack",
    ".shield--rear.ship-display__shield in .ship-display__silhouette-stack",
    ".shield--left.ship-display__shield in .ship-display__silhouette-stack",
    ".shield--right.ship-display__shield in .ship-display__silhouette-stack",

    # Weapons display: three layers around one silhouette.
    ".weapons-display__silhouette in .weapons-display__pane",
    ".weapons--above.weapons-display__weapons in .weapons-display__pane",
    ".weapons--below.weapons-display__weapons in .weapons-display__pane",

    # The mode button and its tooltip. The tip (30) IS contained, by .mode-btn.
    ".mode-btn in .bc-panel__body",
}

# Elements JS creates, which no static walk can see, and the container each is
# appended to. The container must create a stacking context — this is exactly
# the assertion that was missing when .sm-label escaped #star-map-labels.
_JS_CREATED = {
    ".sm-label": "star-map-labels",          # star_map.js
    ".sm-label--disc": "star-map-labels",
    ".sm-here-arrow": "star-map-labels",
    ".cp-capture-modal": "configuration-panel",   # configuration_panel.js
}


def _attr(attrs, name):
    m = re.search(name + r'\s*=\s*"([^"]*)"', attrs)
    return m.group(1) if m else ""


def _document():
    """Every element in index.html, each carrying its ancestor chain."""
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    elements, stack = [], []
    for m in _TAG.finditer(html):
        closing, tag, attrs, self_close = m.groups()
        if closing:
            while stack and stack.pop()["tag"] != tag:
                pass
            continue
        el = {"tag": tag, "id": _attr(attrs, "id"),
              "classes": set(_attr(attrs, "class").split()),
              "style": _attr(attrs, "style"), "chain": list(stack)}
        elements.append(el)
        if not self_close and tag not in _VOID:
            stack.append(el)
    return elements


def _sheets():
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    return [ASSETS / h for h in
            re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)]


def _rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _matches(sel, el, chain):
    """Descendant combinators, #id, .class and tags — all these sheets use."""
    if any(c in sel for c in ">+~:"):
        return False
    parts = sel.split()

    def compound(part, e):
        for tok in re.findall(r"[#.]?[\w-]+", part):
            if tok.startswith("#"):
                if e["id"] != tok[1:]:
                    return False
            elif tok.startswith("."):
                if tok[1:] not in e["classes"]:
                    return False
            elif e["tag"] != tok:
                return False
        return True

    if not compound(parts[-1], el):
        return False
    i = 0
    for part in parts[:-1]:
        while i < len(chain) and not compound(part, chain[i]):
            i += 1
        if i == len(chain):
            return False
        i += 1
    return True


def _specificity(sel):
    return (sel.count("#"), sel.count("."),
            len(re.findall(r"(?:^|\s)[a-zA-Z]", sel)))


def _prop(el, name):
    """Winning value of `name` for `el`: highest (specificity, source order)."""
    best, best_key = None, None
    for order, path in enumerate(_sheets()):
        for selectors, body in _rules(path.read_text(encoding="utf-8")):
            decls = re.findall(name + r"\s*:\s*([^;]+)", body)
            if not decls:
                continue
            for sel in selectors.split(","):
                sel = sel.strip()
                if sel and _matches(sel, el, el["chain"]):
                    key = (_specificity(sel), order)
                    if best_key is None or key >= best_key:
                        best, best_key = decls[-1].strip(), key
    inline = re.search(name + r"\s*:\s*([^;]+)", el.get("style", ""))
    return inline.group(1).strip() if inline else best


def _name(el):
    return "#" + el["id"] if el["id"] else "." + ".".join(sorted(el["classes"]))


def _creates_stacking_context(el):
    """A positioned element with an integer z-index. Enough for these sheets:
    none of them uses transform/filter/opacity to make a context."""
    z = _prop(el, "z-index")
    pos = (_prop(el, "position") or "static")
    return bool(z and re.match(r"-?\d+$", z) and pos != "static")


def _escapes():
    out = set()
    for el in _document():
        z = _prop(el, "z-index")
        if not z or not re.match(r"-?\d+$", z):
            continue
        anc = next((a for a in reversed(el["chain"])
                    if (_prop(a, "position") or "static") != "static"), None)
        if anc is None:
            continue                      # top-level: nothing to escape into
        if not _creates_stacking_context(anc):
            out.add(_name(el) + " in " + _name(anc))
    return out


def test_no_new_z_index_escapes_a_stacking_context():
    """A z-index whose nearest positioned ancestor forms no stacking context
    leaks into a scope nobody reasoned about. Three shipped bugs had that
    shape; this pins the set so a fourth cannot arrive quietly."""
    found = _escapes()

    new = found - _KNOWN_ESCAPES
    assert not new, (
        "z-index escaping its layer — give the CONTAINER a z-index so the "
        "value stays local, or add it to _KNOWN_ESCAPES with a reason:\n  "
        + "\n  ".join(sorted(new)))

    fixed = _KNOWN_ESCAPES - found
    assert not fixed, (
        "these escapes are contained now — delete them from _KNOWN_ESCAPES "
        "to keep the ratchet honest:\n  " + "\n  ".join(sorted(fixed)))


def test_containers_of_js_created_layers_form_stacking_contexts():
    """The check that was missing when the star map broke.

    A JS-injected element carrying a z-index is invisible to the walk above,
    so its container is asserted directly. #star-map-labels had `position:
    absolute` and NO z-index, so `.sm-label` (2) and `.sm-here-arrow` (3)
    escaped it and outranked the target popup at `auto`.
    """
    by_id = {el["id"]: el for el in _document() if el["id"]}
    for selector, container_id in sorted(_JS_CREATED.items()):
        container = by_id.get(container_id)
        assert container is not None, (
            selector + " is appended to #" + container_id
            + ", which is not in index.html")
        assert _creates_stacking_context(container), (
            "#" + container_id + " holds JS-created " + selector
            + ", which carries a z-index — the container must create a "
              "stacking context or that value escapes the layer")
