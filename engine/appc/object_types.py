"""BC's `CT_*` object type-tags, and the map to the classes our shim uses.

BC's `CT_*` are integer type tags (measured by probe q13: `CT_NEBULA` is
32782, `CT_SHIP` 32776, `CT_ASTEROID_FIELD` 32788 -- see
`engine/appc/constants_generated.py`).  Our shim historically bound the NAME
to the CLASS instead, because every one of our type-dispatch consumers filters
with `isinstance`: `SetClass.GetClassObjectList`, `ObjectClass.IsTypeOf`,
`ShipSubsystem.IsTypeOf`, `ShipClass.StartGetSubsystemMatch` and
`TGModelPropertySet.GetPropertiesByType`.

Both representations now coexist.  `App.CT_*` carries BC's integer, and this
registry resolves that integer back to the class the `isinstance` filters
need.  Consumers call `resolve_class()`, which accepts either form, so engine
code that still passes a class keeps working unchanged.

The registry is populated by `App.py`'s `CT_*` block (the one place that knows
both the tag -- read from the generated table, never hand-typed -- and the
class it selects).
"""

_BY_TAG: dict = {}
_BY_CLASS: dict = {}

# Set once App.py's CT_ block has run.  `_ensure_populated` uses it to avoid
# re-entering an in-progress `import App`.
_populating = False


def register(tag, cls) -> None:
    """Bind BC's integer type tag `tag` to the class our filters use.

    First registration of a class wins for the reverse direction, so a class
    reachable from two tags reports the tag it was first registered under.
    """
    tag = int(tag)
    _BY_TAG[tag] = cls
    _BY_CLASS.setdefault(cls, tag)


def _ensure_populated() -> None:
    """Import `App` once if nothing has registered yet.

    Registration happens as a side effect of importing `App`, and every real
    caller reaches this only through an object `App` created.  But a test (or
    a future caller) that imports an `engine.appc` module directly would
    otherwise get an empty registry and a silently-empty query -- exactly the
    failure mode this module exists to prevent.  Guarded against re-entry so
    a lookup made *during* `App`'s own import cannot loop.

    A failing `import App` is deliberately allowed to propagate: an engine
    with no App module is catastrophically broken, and a loud ImportError
    beats every type query silently answering "no matches".
    """
    global _populating
    if _BY_TAG or _populating:
        return
    _populating = True
    try:
        import App  # noqa: F401  (import side effect: the CT_ block registers)
    finally:
        _populating = False


def class_for(tag):
    """The class BC's integer type tag `tag` selects, or None.

    `bool` is rejected explicitly: `True`/`False` are `int` subclasses in
    Python, and a stray boolean must not resolve to whatever sits at tag 1.
    """
    if not isinstance(tag, int) or isinstance(tag, bool):
        return None
    _ensure_populated()
    return _BY_TAG.get(tag)


def tag_for(cls):
    """BC's integer type tag for `cls`, or None if it is not registered."""
    if not isinstance(cls, type):
        return None
    _ensure_populated()
    return _BY_CLASS.get(cls)


def resolve_class(value):
    """Normalise either representation to the class an `isinstance` filter
    needs, or None.

    `None` for anything unrecognised -- including a fall-through `_NamedStub`
    for an undefined `App.CT_*`, and an integer tag with no registered class.
    Callers treat None as "matches nothing", which is what every SDK
    while-loop and list-comprehension consumer already expects.
    """
    if isinstance(value, type):
        return value
    return class_for(value)


def registered_tags():
    """Every tag currently registered (test/introspection helper)."""
    _ensure_populated()
    return tuple(_BY_TAG)
