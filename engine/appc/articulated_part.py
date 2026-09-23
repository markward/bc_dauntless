"""The ArticulatedPartProperty template -- a ship part that moves or comes off.

A BC property template like any other, because a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetFoo(...); RegisterLocalTemplate(X)`.
Choosing that shape means a modded ship can carry its own rig in its own
hardpoint file with no second format, and that `hardpoint_overrides.py` can
carry it for stock ships with no new file. See spec section 2.2.

The template NAME is the NIF node name. One string, and the same key `find()`
already uses. A node named identically to a subsystem would collide in
FindByName; no stock ship does this. Accepted, not designed around.
"""

STATES = ("cruise", "yellow", "red", "warp")


class ArticulatedPartProperty:
    def __init__(self, name):
        self._name = str(name)
        self._pivot = (0.0, 0.0, 0.0)
        self._axis = (0.0, 1.0, 0.0)     # ship-forward
        self._angles = {}
        self._detach = None

    # ---- BC-style setters (what a hardpoint file calls) ----------------
    def SetPivot(self, x, y, z):
        self._pivot = (float(x), float(y), float(z))

    def SetAxis(self, x, y, z):
        self._axis = (float(x), float(y), float(z))

    def SetStateAngle(self, state, degrees):
        if state not in STATES:
            raise ValueError(
                "unknown articulation state %r; expected one of %r"
                % (state, STATES))
        self._angles[state] = float(degrees)

    def SetDetachFraction(self, fraction):
        self._detach = float(fraction)

    def GetName(self):
        return self._name

    # ---- readers -------------------------------------------------------
    @property
    def pivot(self):
        return self._pivot

    @property
    def axis(self):
        return self._axis

    @property
    def detach_fraction(self):
        """Fraction of MAX hull that shears this part, or None for a part that
        does not come off. None, never 0.0 -- absent must not read as
        'detaches instantly'."""
        return self._detach

    def angle_for(self, state):
        """Degrees about the hinge in `state`. Unset is 0.0: the NIF pose,
        i.e. 'as modelled', which is the right default for a part whose
        author has not considered that state."""
        return self._angles.get(state, 0.0)


def ArticulatedPartProperty_Create(name):
    """Factory, matching BC's `App.<Type>_Create` convention."""
    return ArticulatedPartProperty(name)
