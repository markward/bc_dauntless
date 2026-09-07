"""Comment-stripping for inspect.getsource() ordering guards.

Several tests in this project assert call ORDER by searching
``inspect.getsource()`` text for two call spellings and comparing their
string indices (e.g. "boot must call r.init() before r.cef_initialize()").
A bare substring search cannot tell a real call from a COMMENT that merely
mentions one -- a comment explaining a LATER call, or an adversarial one
planted above the real call, reads identically to the call itself and
silently satisfies the assertion either way.

This has broken guards on this branch more than once, in more than one
file, which is why it now lives here instead of being copy-pasted per
file: every ``inspect.getsource`` ordering assertion in the test suite must
route through ``code_only`` first, so a fix to the stripping logic (or a
case it misses) only needs to happen in one place.
"""


def code_only(src: str) -> str:
    """`src` with `#` comments removed.

    A ``#`` inside a string literal is stripped too. Harmless for the
    ordering guards this exists for (none of the spellings they search for
    appear inside a string literal in the functions they inspect), but it
    means this is not a real tokenizer -- don't reach for it outside that
    narrow use.
    """
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())
