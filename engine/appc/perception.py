"""What an observer can perceive — the read-time half of the contact model.

engine.appc.contact_index holds what EXISTS, bucketed by set. This module
answers the per-observer question, which cannot be stored: the same ship is
perceivable to one observer and not another at the same instant, so a stored
answer would have to be per-observer-per-frame.

STAGE 1 SCOPE: membership only. Detectability (range, cloak, nebula) is still
applied downstream by engine.ui.target_list_visibility exactly as before, so
this change alters no behaviour. Stage 3 folds those rules in here and deletes
that module; stage 4 changes the rules themselves. See
docs/superpowers/specs/2026-08-16-contact-index-and-perception-design.md.
"""
from __future__ import annotations

from engine.appc import contact_index


def contacts_for(observer) -> tuple:
    """Ships in *observer*'s containing set that it may target, excluding
    *observer* itself.

    Empty when there is no observer or it is in no set — which is also what
    makes warp self-correcting: mid-warp the player sits alone in the
    _WarpTransit set, so the list empties without anyone clearing it.

    The targetable gate is the mission's authored flag (SetTargetable), read
    through to the object rather than stored here: the mission owns it and
    flips it on reveal beats, and a copy would go stale on any missed write.
    """
    if observer is None:
        return ()
    pSet = observer.GetContainingSet() if hasattr(observer, "GetContainingSet") else None
    # A real SetClass exposes _objects; a _Stub or None does not. hasattr()
    # cannot discriminate — TGObject.__getattr__ answers every name.
    if pSet is None or not hasattr(pSet, "_objects"):
        return ()
    return tuple(
        s for s in contact_index.ships_in(pSet)
        if s is not observer and s.IsTargetable()
    )
