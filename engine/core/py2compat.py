"""Runtime helpers reproducing Python-2 semantics for SDK script code.

The SDK is Python 1.5/2.x and is ground truth; we run it unmodified under
CPython 3, so anywhere the language itself changed meaning we have to put the
old meaning back. Most of that is done by AST transforms at import time
(tools/mission_harness.py, tests/conftest.py); this module holds the pieces
those transforms need at runtime.
"""


def py2_cmp(op: str, left, right):
    """Evaluate ``left <op> right`` with Python 2's cross-type ordering.

    Python 2 gave *every* pair of objects an ordering: unrelated types compared
    by type name, except that numbers always sorted before non-numbers. Python
    3 raises TypeError for ordering comparisons between unrelated types.

    Almost always this is a plain pass-through — the fallback only runs when
    the comparison would otherwise have raised, so code comparing genuine
    numbers is unaffected apart from the call itself.

    The one shipped SDK site that needs it is
    ``AI/Compound/DockWithStarbase.py:94``::

        if vDiff.SqrLength < 0.5:     # no parens -- a bound METHOD vs a float

    Under Python 2 the float is the smaller operand, so BC never takes that
    branch and keeps the unitized away-direction it computed two lines earlier.
    We reproduce that answer rather than the author's evident intent: calling
    the method would fire the branch on a degenerate vector, which BC never did
    (BC instead divides by zero shortly after, which needs an object exactly
    coincident with the docking entry).

    ``==`` / ``!=`` never raised in Python 2 either — they fall back to identity
    — so they need no special handling and are passed straight through.
    """
    try:
        return _OPS[op](left, right)
    except TypeError:
        pass
    # Python 2's rule: numbers sort before everything else; otherwise order by
    # type name. bool is a number too, and complex is deliberately excluded --
    # Python 2 refused to order complex numbers as well.
    def _rank(v):
        return (0, "") if isinstance(v, (int, float)) else (1, type(v).__name__)

    lhs, rhs = _rank(left), _rank(right)
    if lhs == rhs:
        # Same non-numeric type name and still unorderable: Python 2 fell back
        # to comparing addresses. Identity is the stable, reproducible stand-in.
        lhs, rhs = (id(left),), (id(right),)
    return _OPS[op](lhs, rhs)


import operator as _operator

_OPS = {
    "<": _operator.lt,
    "<=": _operator.le,
    ">": _operator.gt,
    ">=": _operator.ge,
    "==": _operator.eq,
    "!=": _operator.ne,
}
