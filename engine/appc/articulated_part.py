"""The ArticulatedPartProperty template -- a ship part that moves or comes off.

A BC property template like any other, because a hardpoint file is nothing but
`X = App.Something_Create(name); X.SetAnchor(...); X.SetStatePose(...);
RegisterLocalTemplate(X)`. Choosing that shape means a modded ship can carry
its own rig in its own hardpoint file with no second format, and that
`hardpoint_overrides.py` can carry it for stock ships with no new file. See
spec section 2.2.

`SetAnchor`/`SetTransitionSeconds`/`SetStatePose`/`SetBreakFraction` are the
current authoring surface (spec §3, §6). The legacy `SetPivot`/`SetAxis`/
`SetStateAngle`/`SetDetachFraction` calls are still accepted and read: a
state with a legacy angle but no `SetStatePose` for that state converts
through the hinge at read time.

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
        self._range_cache = None         # invalidated by SetStateAngle
        self._anchor = None
        self._transition = 2.0
        self._poses = {}                 # state -> p6
        self._pivot_set = False

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
        # Invalidate directly at the one place `_angles` can change, rather
        # than tracking a dirty flag -- `articulation.ease_angle`'s rate
        # depends on `angle_range`, so a re-authored angle must take effect
        # on the very next tick, not run at the old rate silently.
        self._range_cache = None

    def SetDetachFraction(self, fraction):
        self._detach = float(fraction)

    def GetName(self):
        return self._name

    # ---- the pose surface (spec 2026-09-25) -------------------------------
    def SetAnchor(self, x, y, z):
        self._anchor = (float(x), float(y), float(z))

    def SetTransitionSeconds(self, seconds):
        self._transition = float(seconds)

    def SetStatePose(self, state, tx, ty, tz, rx, ry, rz):
        if state not in STATES:
            raise ValueError(
                "unknown articulation state %r; expected one of %r"
                % (state, STATES))
        self._poses[state] = tuple(float(v) for v in (tx, ty, tz, rx, ry, rz))

    def SetBreakFraction(self, fraction):
        self._detach = float(fraction)

    @property
    def anchor(self):
        """Swing centre (ship units, body frame), or None. A legacy hinge
        with no explicit anchor anchors at its pivot."""
        if self._anchor is not None:
            return self._anchor
        if self._angles:
            return self._pivot
        return None

    @property
    def transition_seconds(self):
        return self._transition

    @property
    def break_fraction(self):
        """Fraction of the ship's MAX hull accumulated ON this part that
        shears it, or None (never breaks)."""
        return self._detach

    def pose6_for(self, state):
        """(tx,ty,tz,rx,ry,rz) authored for `state`, or None. A legacy angle
        converts through the hinge."""
        if state in self._poses:
            return self._poses[state]
        if state in self._angles:
            from engine.appc import part_pose
            return part_pose.pose_to6(part_pose.hinge_pose(
                self._pivot, self._axis, self._angles[state]))
        return None

    def pose_for(self, state):
        """The part's pose in `state`; the NIF pose (identity) when unset."""
        from engine.appc import part_pose
        if state in self._poses:
            return part_pose.pose_from6(self._poses[state])
        if state in self._angles:
            return part_pose.hinge_pose(self._pivot, self._axis,
                                        self._angles[state])
        return part_pose.IDENTITY

    def authored_states(self):
        return tuple(s for s in STATES
                     if s in self._poses or s in self._angles)

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

    @property
    def angle_range(self) -> float:
        """Peak-to-peak spread of the authored angle across every state --
        `engine.appc.articulation.ease_angle`'s per-part rate normaliser.

        Cached because it is read every tick for every part that is easing;
        invalidated by `SetStateAngle` (the only way `_angles` can change),
        not by a TTL or an identity-keyed external cache, so re-authoring an
        angle -- the literal subject of this feature -- takes effect on the
        very next tick rather than running at the old rate silently. Lives
        on the instance, so it is released exactly when the part itself is
        (e.g. by `reset()` dropping `_BY_LEAF`'s references), never longer.
        """
        if self._range_cache is None:
            values = [self._angles.get(s, 0.0) for s in STATES]
            self._range_cache = max(values) - min(values)
        return self._range_cache


def ArticulatedPartProperty_Create(name):
    """Factory, matching BC's `App.<Type>_Create` convention."""
    return ArticulatedPartProperty(name)


# ── Per-leaf snapshot ─────────────────────────────────────────────────────
#
# WHY A SNAPSHOT AND NOT A LIVE QUERY: TGModelPropertyManager._local
# (engine/appc/properties.py:1021) is a {name: prop} dict that
# ClearLocalTemplates() wipes on every ship load (properties.py:1033, called
# from loadspacehelper.CreateShip before each reload). It holds only the
# MOST RECENTLY loaded ship's templates -- a per-tick parts_for_leaf(leaf)
# reading the manager live would silently return whatever ship happened to
# load last. Templates are load-time scaffolding, consumed at construction;
# per-ship data has to be copied out of the manager at the moment it exists,
# which is what snapshot_for_leaf does.
_BY_LEAF: dict = {}


def snapshot_for_leaf(leaf) -> None:
    """Copy every ArticulatedPartProperty currently registered as a LOCAL
    template into the snapshot kept for `leaf`.

    Call this immediately after `leaf`'s hardpoint file has finished
    registering its templates -- whether that registration came from
    hardpoint_overrides.apply(leaf) (a stock ship) or the hardpoint file's
    own module body (a modded ship carrying its own rig): both are done by
    the time sdk_overrides.on_sdk_module_exec calls this.

    Reaches TGModelPropertyManager's private `_local` store directly --
    there is no public "list every local template" method (FindByName and
    FindByNameAndType both require already knowing a name). Accepted
    coupling: adding a public enumeration method for this one caller would
    be more surface than the one snapshot site needs.
    """
    import App
    local = getattr(App.g_kModelPropertyManager, "_local", {})
    _BY_LEAF[leaf] = tuple(
        p for p in local.values() if isinstance(p, ArticulatedPartProperty))


def parts_for_leaf(leaf):
    """The articulated parts snapshotted for `leaf`, as a tuple.

    Returns () for a leaf with no snapshot -- an unrigged ship is the
    overwhelmingly common case and must cost nothing and never raise.
    """
    return _BY_LEAF.get(leaf, ())


def reset() -> None:
    """Clear every snapshot. Call on mission swap, and from test teardown --
    _BY_LEAF is process-wide state."""
    _BY_LEAF.clear()
