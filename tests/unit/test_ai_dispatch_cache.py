"""_dispatch_ai resolves its handler through a per-type cache.

The cache replaced an ordered isinstance chain, so two properties have to
hold or AI nodes get dispatched to the wrong handler:

  * ORDER is preserved. The chain is order-sensitive — a class that is both a
    BuilderAI and a PreprocessingAI must resolve to builder, because that is
    what the chain did.
  * issubclass(type(x), C) really is isinstance(x, C) here. That equivalence
    breaks if any class uses a custom __instancecheck__ (ABCs, virtual
    subclasses) or overrides __class__. None do today; this test fails the
    moment one starts, rather than silently mis-dispatching.
"""
from engine.appc import ai_driver
from engine.appc.ai import (
    BuilderAI, ConditionalAI, PlainAI, PreprocessingAI, PriorityListAI,
    RandomAI, SequenceAI,
)

_AI_CLASSES = (BuilderAI, PreprocessingAI, ConditionalAI, PriorityListAI,
               SequenceAI, RandomAI, PlainAI)


def test_no_class_breaks_the_isinstance_equivalence():
    for cls in _AI_CLASSES:
        meta = type(cls)
        custom_instancecheck = any(
            "__instancecheck__" in k.__dict__
            for k in meta.__mro__ if k is not type)
        assert not custom_instancecheck, (
            "%s's metaclass defines __instancecheck__; issubclass(type(x), C) "
            "no longer equals isinstance(x, C) and _resolve_dispatch is unsafe"
            % cls.__name__)
        custom_class_attr = any(
            "__class__" in k.__dict__ for k in cls.__mro__ if k is not object)
        assert not custom_class_attr, (
            "%s overrides __class__; type(x) no longer reflects isinstance"
            % cls.__name__)


def test_each_class_resolves_to_its_own_handler():
    expected = {
        BuilderAI: ai_driver._tick_builder,
        PreprocessingAI: ai_driver._tick_preprocessing,
        ConditionalAI: ai_driver._tick_conditional,
        PriorityListAI: ai_driver._tick_priority_list,
        SequenceAI: ai_driver._tick_sequence,
        RandomAI: ai_driver._tick_random,
        PlainAI: ai_driver._tick_plain,
    }
    for cls, handler in expected.items():
        assert ai_driver._resolve_dispatch(cls) is handler, cls.__name__


def test_resolution_matches_the_ordered_isinstance_chain():
    """Reference: the chain exactly as _dispatch_ai used to run it."""
    def reference(node):
        if isinstance(node, BuilderAI):        return ai_driver._tick_builder
        if isinstance(node, PreprocessingAI):  return ai_driver._tick_preprocessing
        if isinstance(node, ConditionalAI):    return ai_driver._tick_conditional
        if isinstance(node, PriorityListAI):   return ai_driver._tick_priority_list
        if isinstance(node, SequenceAI):       return ai_driver._tick_sequence
        if isinstance(node, RandomAI):         return ai_driver._tick_random
        if isinstance(node, PlainAI):          return ai_driver._tick_plain
        return None

    for cls in _AI_CLASSES:
        node = cls.__new__(cls)
        assert ai_driver._resolve_dispatch(cls) is reference(node), cls.__name__


def test_a_subclass_resolves_like_its_base():
    class MyPlain(PlainAI):
        pass

    assert ai_driver._resolve_dispatch(MyPlain) is ai_driver._tick_plain


def test_earlier_chain_entries_win_for_a_multiple_base():
    """Order sensitivity, stated as a test rather than a comment."""
    class BuilderAndPlain(BuilderAI, PlainAI):
        pass

    assert ai_driver._resolve_dispatch(BuilderAndPlain) is ai_driver._tick_builder


def test_an_unrecognised_type_resolves_to_nothing():
    class NotAnAI:
        pass

    assert ai_driver._resolve_dispatch(NotAnAI) is None
