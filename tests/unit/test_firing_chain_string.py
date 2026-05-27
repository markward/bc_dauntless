"""WeaponSystemProperty.SetFiringChainString / GetFiringChains.

Format observed in SDK hardpoints (only Galaxy + Sovereign use a
non-empty value): ``"0;Single;123;Dual;53;Quad"``. Reading it as
alternating <tube-index-digits>;<chain-label> pairs:

  ``0;Single``  → chain "Single" fires tube 0
  ``123;Dual``  → chain "Dual"   fires tubes 1, 2, 3
  ``53;Quad``   → chain "Quad"   fires tubes 5, 3

The label words (Single/Dual/Quad) don't match the tube counts (1/3/2),
so they're treated as opaque names — the parser doesn't reason about
them. Player UI / AI selects a chain by index; the digit string in
each pair drives the actual fire pattern.

Empty input → no chains. Most ships set ``""``.
"""
from engine.appc.localization import TGString
from engine.appc.properties import TorpedoSystemProperty


def test_empty_chain_string_yields_no_chains():
    p = TorpedoSystemProperty("Torpedoes")
    p.SetFiringChainString(TGString(""))
    assert p.GetFiringChains() == []


def test_galaxy_chain_string_parses_three_groups():
    p = TorpedoSystemProperty("Torpedoes")
    p.SetFiringChainString(TGString("0;Single;123;Dual;53;Quad"))
    chains = p.GetFiringChains()
    assert chains == [
        ("Single", [0]),
        ("Dual",   [1, 2, 3]),
        ("Quad",   [5, 3]),
    ]


def test_set_firing_chain_string_accepts_plain_str():
    """Engine callers that pass a Python str (not a TGString) work too —
    avoids forcing every test fixture to wrap strings in TGString."""
    p = TorpedoSystemProperty("Torpedoes")
    p.SetFiringChainString("0;Single")
    assert p.GetFiringChains() == [("Single", [0])]


def test_chain_string_with_unpaired_trailing_indices_ignores_them():
    """Defensive: malformed input drops the lone trailing digit group
    rather than raising."""
    p = TorpedoSystemProperty("Torpedoes")
    p.SetFiringChainString(TGString("0;Single;12"))
    # Second group has no label → drop.
    assert p.GetFiringChains() == [("Single", [0])]
