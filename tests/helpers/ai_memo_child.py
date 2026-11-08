"""Children for tests/unit/test_ai_native_stock_memo.py that must run in a
fresh interpreter (final-fix wave of phase 6 AI part 2): a memo overflow
whose released keys store into the same memo, and the references the AI
hosts keep when they are first built. Each is a no-op unless AI_MEMO_CHILD
is set (the parent sets it)."""
import os
import sys
import weakref

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AI_MEMO_CHILD") != "1",
                                reason="only runs as a child")


def test_child_reentrant_surface_memo_overflow():
    import _dauntless_host as h
    if not h.ai_memo_status()["enabled"]:
        pytest.skip("the memos are off on this Python")
    watched = ({},)
    tags = h.ai_memo_tags(watched)

    class Key:
        pass

    fresh = []

    def stored_while_dying(_ref):
        k = Key()
        fresh.append(k)
        h.ai_memo_put(k, watched, h.ai_memo_tags(watched), "fresh")

    refs = []
    for i in range(64):                       # the memo's bound
        k = Key()
        refs.append(weakref.ref(k, stored_while_dying))
        h.ai_memo_put(k, watched, tags, i)
        del k                                 # held by the memo alone
    assert not fresh
    last = Key()
    h.ai_memo_put(last, watched, tags, "last")   # full: emptied first
    assert len(fresh) == 64
    miss = object()
    assert h.ai_memo_get(last, miss) == "last"
    assert [h.ai_memo_get(k, miss) for k in fresh] == ["fresh"] * 64


def test_child_host_init_holds_one_reference_per_kept_string():
    import App
    import engine.appc.math  # noqa: F401  (imported before counting)
    from engine.appc import ai_native, ai_optimized  # noqa: F401
    from engine.appc import object_types, objects  # noqa: F401
    import _dauntless_host as h
    s = sys.intern("surface")
    before = sys.getrefcount(s)
    with pytest.raises(TypeError):             # builds the avoid host first
        h.combat_ai_avoid_scan(None, None, 0.0, None)
    try:
        h.combat_ai_target_rating(object(), object(), App)
    except TypeError:                         # the two-argument binding
        h.combat_ai_target_rating(object(), object())
    with pytest.raises(NameError):            # the fire host, then no App
        h.combat_ai_fire_update(object(), 0.0, {})
    # One each: avoid's and fire's ("<kind>", "surface") note arguments and
    # the rating's reason string.
    assert sys.getrefcount(s) - before == 3
