"""RockClass: a BC asteroid as a lean body, not a ship.

Spec: docs/superpowers/specs/2026-09-30-rock-class-design.md.

A RockClass IS a ShipClass (missions ShipClass_Cast rocks: E1M2.py:1257/1314,
E2M1.py:649/1079), but the AI, motion and subsystem loops skip it
(ship_iter.iter_non_rock_ships). A ship becomes a rock when its properties
land with genus GENUS_ASTEROID -- ShipClass_Create only ever sees a name.
"""
import engine.dev_mode as dev_mode
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass


class RockClass(ShipClass):
    """No __slots__, no __init__: instances are made by reassigning the
    __class__ of a live ShipClass, so the layout must stay identical."""

    def _become_rock(self) -> None:
        d = self.__dict__
        d.setdefault("_model_override", None)
        d.setdefault("_rock_family", "silicate")
        d.setdefault("_angular_space", PhysicsObjectClass.DIRECTION_WORLD_SPACE)
        d.setdefault("_rock_generation", 0)
        self._ai = None
        # Spec §1: "Shield maxima are zeroed so shields_block is false" --
        # unconditionally, whatever the hardpoint authored. Stock asteroid
        # hardpoints already declare every face at MaxShields 0, but a
        # genus-3 hardpoint is not guaranteed to (a modded rock could reuse
        # a shielded template), so zero every face here rather than trust
        # the source. Idempotent: re-zeroing an already-zero face is a
        # no-op. GetShields() is None until a hardpoint declares a
        # ShieldProperty at all (SetupProperties Pass 3 scrubs the
        # default-constructed slot when none was claimed).
        shields = self.GetShields()
        if shields is not None:
            for face in range(shields.NUM_SHIELDS):
                shields.SetMaxShields(face, 0.0)
                shields.SetCurrentShields(face, 0.0)

    def SetAI(self, ai, *_extra) -> None:
        if ai is not None:
            dev_mode.log_swallowed(
                "SetAI on a rock ignored",
                RuntimeError(str(self.GetName())))

    def ClearAI(self, *_extra) -> None:
        self._ai = None


def is_rock(obj) -> bool:
    return isinstance(obj, RockClass)


def maybe_become_rock(ship) -> bool:
    """Switch `ship` to RockClass if its genus says asteroid. Idempotent."""
    import App
    if isinstance(ship, RockClass):
        ship._become_rock()
        return True
    if type(ship) is not ShipClass:
        return False          # a ShipClass subclass we don't own: leave it
    try:
        genus = int(ship.GetGenus())
    except Exception:
        return False
    if genus != App.GENUS_ASTEROID:
        return False
    ship.__class__ = RockClass
    ship._become_rock()
    return True
