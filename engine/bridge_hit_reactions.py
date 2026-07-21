# engine/bridge_hit_reactions.py
"""Direction + severity aware bridge-crew hit reactions.

On a player-ship WeaponHitEvent we compute the impact bearing relative to the
ship's starboard axis (GetCol(0)) and the damage severity, pick the SDK reaction
class (HitStanding/HitHardStanding/Blast/ReactLeft/ReactRight), resolve each
visible officer's registered key for it, and submit the SDK-built clip sequence
to the character controller at reaction priority (preempts idle).
"""
from engine.bridge_idle_gestures import build_sequence_clips

# Damage severity bands (tune against engine/appc/combat.py magnitudes).
_LIGHT_MAX = 15.0
_HARD_MIN = 50.0
_BLAST_MIN = 120.0


def select_reaction(bearing_dot, damage) -> str:
    if damage >= _BLAST_MIN:
        return "Blast"
    if damage >= _HARD_MIN:
        return "HitHardStanding"
    if damage >= _LIGHT_MAX:
        return "HitStanding"
    return "ReactRight" if bearing_dot >= 0.0 else "ReactLeft"


def _bearing_dot(ship, hit_point) -> float:
    """Sign>0 = starboard (right), <0 = port (left), via the ship's right axis."""
    try:
        loc = ship.GetWorldLocation()
        right = ship.GetWorldRotation().GetCol(0)
        dx = hit_point.GetX() - loc.GetX()
        dy = hit_point.GetY() - loc.GetY()
        dz = hit_point.GetZ() - loc.GetZ()
        return dx * right.GetX() + dy * right.GetY() + dz * right.GetZ()
    except Exception:
        return 0.0


class HitReactionHandler:
    def __init__(self, controller, *, get_player, get_characters, anim_mgr):
        # `controller` is retained only to keep the host loop's constructor
        # call unchanged; the handler now enqueues through the CharacterClass
        # queue door directly (SetCurrentAnimation) rather than submitting to
        # the controller.
        self._controller = controller
        self._get_player = get_player
        self._get_characters = get_characters
        self._anim_mgr = anim_mgr

    def on_weapon_hit(self, event) -> None:
        player = self._get_player()
        if player is None or event.GetTarget() is not player:
            return
        hit_point = event.GetHitPoint()
        bearing = _bearing_dot(player, hit_point) if hit_point is not None else 0.0
        reaction = select_reaction(bearing, float(event.GetDamage()))
        for ch in self._get_characters():
            if getattr(ch, "_render_instance", None) is None or ch.IsHidden():
                continue
            module_path = self._resolve_key(ch, reaction)
            if not module_path:
                continue
            clips = build_sequence_clips(module_path, ch, self._anim_mgr)
            if not clips:
                continue
            # RE order (DoCrewReactions): ClearExtraAnimations() runs BEFORE
            # the IsGoingToAnimate() gate -- clear the interruptable set
            # first, then enqueue the reaction only if no committed
            # (cat2/3/4) animation is already queued. Replicates what
            # PlayAnimation(key, -1, 0) does observably (mode -1 ->
            # CAT_NON_INTERRUPTABLE). No on_complete.
            ch.ClearExtraAnimations()
            if not ch.IsGoingToAnimate():
                ch.SetCurrentAnimation(clips, ch.CAT_NON_INTERRUPTABLE, 0, None)

    @staticmethod
    def _resolve_key(character, reaction) -> str:
        """Find the character's registered reaction by SDK builder name.

        The registered KEY is location-prefixed and artist-named (e.g. Blast is
        keyed "<loc>Fly", not "<loc>Blast"), so matching on key suffix is
        unreliable.  Instead we match on the module path's function name
        (entry[1].rsplit('.', 1)[-1]), which equals select_reaction's return
        value exactly — it IS the CommonAnimations function name.

        Returns the module path (entry[1]), or '' if the character lacks it.
        """
        for entry in getattr(character, "_animations", []):
            if entry and len(entry) >= 2 and \
                    str(entry[1]).rsplit(".", 1)[-1] == reaction:
                return entry[1]
        return ""
