"""implements() caches per (class, name), and the one way that can go stale.

The answer is a property of the CLASS, so it is cached: measured at 100 ships,
2,400 calls/tick (~36,000 per frame) at only 2.2 MRO steps each. Micro-
benchmarked at ~127 ns cached against 315-430 ns walking.

The cache has exactly one hazard -- a class gaining or losing a method after
something has already asked about it. Production never does that (ai_optimized
builds NEW classes with type(), which get their own entries), but a test that
monkey-patches a class would. clear_implements_cache() exists for that, and
this file proves both halves: that the hazard is real, and that the escape
hatch works.
"""
import pytest

from engine.core.ids import implements, clear_implements_cache


@pytest.fixture(autouse=True)
def _clean():
    clear_implements_cache()
    yield
    clear_implements_cache()


class _Base:
    def Present(self):
        pass


class _Derived(_Base):
    def AlsoPresent(self):
        pass


def test_it_still_answers_the_question_correctly():
    obj = _Derived()
    assert implements(obj, "Present") is True          # inherited
    assert implements(obj, "AlsoPresent") is True      # own
    assert implements(obj, "Absent") is False


def test_repeated_queries_agree_with_the_first():
    obj = _Derived()
    first = [implements(obj, n) for n in ("Present", "AlsoPresent", "Absent")]
    for _ in range(50):
        assert [implements(obj, n)
                for n in ("Present", "AlsoPresent", "Absent")] == first


def test_a_negative_answer_is_cached_as_a_negative_not_as_a_miss():
    """False and 'not looked up yet' must not be conflated -- a two-level dict
    using `if not names.get(name)` would re-walk the MRO on every False, i.e.
    fail to cache exactly the case that walks the FULL mro and costs most."""
    obj = _Derived()
    assert implements(obj, "Absent") is False
    from engine.core.ids import _IMPLEMENTS_CACHE
    assert _IMPLEMENTS_CACHE[_Derived]["Absent"] is False


def test_two_classes_do_not_share_answers():
    """The cache is per class; a name present on one and absent on another
    must not bleed across."""
    class _Other:
        def AlsoPresent(self):
            pass

    assert implements(_Derived(), "Present") is True
    assert implements(_Other(), "Present") is False
    assert implements(_Other(), "AlsoPresent") is True


def test_a_subclass_built_later_gets_its_own_entry():
    """ai_optimized builds classes at runtime with type(). A new class must be
    answered on its own MRO, not inherit a cached answer from its base."""
    assert implements(_Base(), "AlsoPresent") is False
    Late = type("Late", (_Base,), {"AlsoPresent": lambda self: None})
    assert implements(Late(), "AlsoPresent") is True
    assert implements(_Base(), "AlsoPresent") is False


def test_monkey_patching_a_class_goes_stale_until_the_cache_is_cleared():
    """The documented hazard, stated as an executable fact rather than a
    warning comment. If this ever starts passing without the clear() call,
    the cache has changed shape and the docstring is lying."""
    class _Patchable:
        pass

    obj = _Patchable()
    assert implements(obj, "AddedLater") is False      # caches the negative

    _Patchable.AddedLater = lambda self: None
    assert implements(obj, "AddedLater") is False, (
        "the cache is supposed to be stale here -- if it is not, the staleness "
        "warning in ids.py is wrong and should be corrected")

    clear_implements_cache()
    assert implements(obj, "AddedLater") is True


def test_clear_is_safe_to_call_on_an_empty_cache():
    clear_implements_cache()
    clear_implements_cache()
    assert implements(_Derived(), "Present") is True
