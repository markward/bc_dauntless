"""Apply the measured App constant table to the shim module.

Additive by default: a name we already define keeps its value unless
`correct_existing` names it.  That split exists because ~584 of our values are
invented and some are COUPLED to consuming code (CT_ class dispatch, CSP_
priority polarity, KBT_ bitmasks) -- those are corrected one audited family at
a time, not in one sweep.
"""

# Qualified name -> why we knowingly differ from the measured value.
DEVIATIONS: dict[str, str] = {
    "PI": "BC's is float32 (3.14159274101); ours is math.pi. Nothing compares "
          "these for equality and the extra precision matters to physics.",
    "HALF_PI": "See PI.",
    "TWO_PI": "See PI.",
    "FOURTH_PI": "See PI.",
}

# Keyboard constants are NOT injected here. App.py's module __getattr__ has a
# dedicated, already-tested mechanism that resolves WC_*/KY_* from the fuller
# engine.appc.input table on first access and memoizes the result into
# vars(App) -- that table covers names this dump omits (the unwired CTRL_/
# ALT_/CAPS_ modifier variants) and is the one production code depends on.
# Pre-populating these names here at import time would run ahead of that
# mechanism and silently replace its resolved values with this dump's, which
# disagree for every key measured so far. Correcting the keyboard family (if
# warranted) is out of scope for this additive pass.
_KEYBOARD_PREFIXES = ("WC_", "KY_")


def _make_synthesized(name, constants, named_stub_factory):
    """A class we do not implement, carrying its measured constants.

    Unknown attributes must keep vending a stub: before this table existed,
    `App.<Cls>` was itself a _NamedStub, so `App.<Cls>.anything` and
    `App.<Cls>(...)` were silent no-ops.  A plain `class X: ...` would turn
    every one of those into AttributeError/TypeError -- trading silent
    breakage for loud crashes across 228 classes we have never needed.
    """
    class _Meta(type):
        def __getattr__(cls, attr):
            return named_stub_factory("%s.%s" % (name, attr))

    def _instance_getattr(self, attr):
        return named_stub_factory("%s.%s" % (name, attr))

    body = dict(constants)
    body["__getattr__"] = _instance_getattr
    body["__init__"] = lambda self, *a, **k: None
    body["__doc__"] = ("Synthesized from the q13 constant dump; not implemented "
                       "by the shim. Unknown attributes still stub.")
    return _Meta(name, (), body)


def apply_constants(module, module_constants, class_constants, deviations,
                    *, correct_existing=frozenset(), named_stub_factory=None):
    """Inject measured constants into `module`.  Returns a counts dict."""
    counts = dict(module_added=0, module_corrected=0, class_added=0,
                  class_corrected=0, classes_synthesized=0, skipped=0)
    ns = module.__dict__

    for name, value in module_constants.items():
        if name in deviations or name[:3] in _KEYBOARD_PREFIXES:
            counts["skipped"] += 1
            continue
        if name not in ns:
            ns[name] = value
            counts["module_added"] += 1
        elif ns[name] != value and name in correct_existing:
            ns[name] = value
            counts["module_corrected"] += 1

    for cls_name, constants in class_constants.items():
        existing = ns.get(cls_name)
        if not isinstance(existing, type):
            ns[cls_name] = _make_synthesized(cls_name, constants,
                                             named_stub_factory)
            counts["classes_synthesized"] += 1
            continue
        for name, value in constants.items():
            qualified = "%s.%s" % (cls_name, name)
            if qualified in deviations:
                counts["skipped"] += 1
                continue
            # Never shadow a real method or attribute with a constant.
            current = next((vars(k)[name] for k in existing.__mro__
                            if name in vars(k)), None)
            if current is None and not any(name in vars(k)
                                           for k in existing.__mro__):
                setattr(existing, name, value)
                counts["class_added"] += 1
            elif callable(current):
                counts["skipped"] += 1
            elif current != value and qualified in correct_existing:
                setattr(existing, name, value)
                counts["class_corrected"] += 1
    return counts
