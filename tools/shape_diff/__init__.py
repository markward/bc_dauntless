"""Shape-geometry diffs for BC set NIFs (spec:
docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md).

Only diffs are committed: indices into the player's own NIF plus geometry
Mark authored. OBJ exports of BC geometry stay in a scratch directory."""


class ShapeDiffError(Exception):
    """A refusal with a message meant for the person running the tool."""
