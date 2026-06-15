"""Loud, terminal-visible tracking for bridge-init Appc stubs.

Distinct from App.py's silent, mission-gated `_StubTracker` (color/analysis).
Every bridge stub calls `stub_call(symbol, detail)` on entry, which prints a
LOUD banner to both stderr and stdout and records the symbol. After
LoadBridge.Load returns, `dump_stub_summary()` prints the set of stubs that
fired — the running "what still needs fleshing out" to-do list. When the
summary prints nothing, the bridge-init sequence is fully faithful.
"""
import sys

_FIRED: set[str] = set()


def stub_call(symbol: str, detail: str = "") -> None:
    banner = "\n*** [BRIDGE-STUB] %s — NOT YET IMPLEMENTED %s\n" % (symbol, detail)
    # Print to BOTH streams so the banner shows regardless of how the host
    # routes output; flush so it is not buffered behind later native logging.
    sys.stderr.write(banner)
    sys.stderr.flush()
    try:
        sys.stdout.write(banner)
        sys.stdout.flush()
    except Exception:
        # stdout may be unavailable in some host contexts; stderr is enough.
        pass
    _FIRED.add(symbol)


def fired() -> set[str]:
    return set(_FIRED)


def dump_stub_summary() -> None:
    if not _FIRED:
        sys.stderr.write(
            "\n*** [BRIDGE-STUB] none fired — bridge init is faithful\n")
        sys.stderr.flush()
        return
    sys.stderr.write(
        "\n*** [BRIDGE-STUB] SUMMARY — %d stub(s) still need fleshing out:\n"
        % len(_FIRED))
    for symbol in sorted(_FIRED):
        sys.stderr.write("***   - %s\n" % symbol)
    sys.stderr.flush()


def reset() -> None:
    _FIRED.clear()
