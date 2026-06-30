"""Interim fallback: route cloak-capable AI ships to the working non-cloak
attack doctrine until the SDK CloakAttack tree is driven correctly.

BC's QuickBattleAI passes ``UseCloaking=1``, so every cloak-capable enemy is
routed by ``AI.Compound.BasicAttack`` through ``CloakAttackWrapper`` → a
``PriorityListAI`` whose ``CloakAttack`` subtree is meant to cloak, approach,
decloak and fire. In our engine that subtree reaches ``SelectTarget`` (with
focus + init correct) but never propagates a target onto the ship, so the whole
attack tree stays dormant and the ship just drifts — "parks up and does nothing"
(verified identical on ``main``; not caused by the cloaking feature work). See
the follow-up doc for the proper fix.

Until ``CloakAttack`` is wired, replace ``CloakAttackWrapper.CreateAI`` so it
returns only the non-cloak ``BasicAttack`` doctrine (``NonFedAttack`` /
``FedAttack``) — which acquires a target and fires correctly. This is exactly
the ``BasicAttack`` tree the wrapper already builds for its "cloak disabled"
branch, so we reuse the SDK's own flag-zeroing rather than fight the
difficulty-prefix logic. Cloak-capable ships therefore fight like normal ships
for now (they will not tactically cloak until step 2 lands).

Reverse this by deleting the ``install_cloak_attack_fallback()`` call once the
CloakAttack doctrine drives SelectTarget.
"""


def _wrap_cloak_wrapper(orig):
    """Return a CreateAI that skips the (currently non-functional) CloakAttack
    PriorityList and hands back the plain non-cloak attack doctrine."""

    def _fallback_create(pShip, *lTargets, **dKeywords):
        # Mirror CloakAttackWrapper's own flag-zeroing, then let BasicAttack
        # route to the non-cloak doctrine (UseCloaking now off → NonFedAttack /
        # FedAttack instead of CloakAttackWrapper — no recursion).
        for sKey in ("UseCloaking", "Easy_UseCloaking", "Hard_UseCloaking"):
            if sKey in dKeywords:
                dKeywords[sKey] = 0
        import AI.Compound.BasicAttack as _ba
        # Splat lTargets so BasicAttack forwards the SAME target nesting it
        # would when routing directly to NonFedAttack/FedAttack. (The stock
        # CloakAttackWrapper passes lTargets as one arg, which double-nests the
        # group — harmless there because its BasicAttack branch only runs while
        # the cloak is disabled, but it would break our directly-returned tree's
        # target resolution.)
        return _ba.CreateAI(pShip, *lTargets, Keywords=dKeywords)

    _fallback_create._cloak_fallback = True
    return _fallback_create


def install_cloak_attack_fallback() -> None:
    """Idempotently replace ``CloakAttackWrapper.CreateAI`` with the non-cloak
    fallback. Safe to call repeatedly; a no-op when the SDK AI tree is absent
    (pure-unit context without ``AI.Compound``)."""
    try:
        import AI.Compound.CloakAttackWrapper as _caw
    except ImportError:
        return
    if not getattr(_caw.CreateAI, "_cloak_fallback", False):
        _caw.CreateAI = _wrap_cloak_wrapper(_caw.CreateAI)
