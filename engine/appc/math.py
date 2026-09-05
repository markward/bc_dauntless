"""
3D math primitives for Phase 1 headless engine.

TGPoint3  — 3-component vector (matches NiPoint3/TGPoint3 from Appc).
TGMatrix3 — 3×3 rotation matrix, row-major (matches NiMatrix3/TGMatrix3).

Phase 1 correctness requirement: position/orientation round-trips are exact;
arithmetic operators produce numerically correct results so that SDK scripts
that compute directions, dot products, and cross products behave correctly.
"""

import math as _math


class TGPoint3:
    """Mutable 3-component vector with x, y, z float attributes."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    # ── Setters ───────────────────────────────────────────────────────────────

    def SetXYZ(self, x: float, y: float, z: float) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def SetX(self, x: float) -> None: self.x = float(x)
    def SetY(self, y: float) -> None: self.y = float(y)
    def SetZ(self, z: float) -> None: self.z = float(z)
    def GetX(self) -> float: return self.x
    def GetY(self) -> float: return self.y
    def GetZ(self) -> float: return self.z

    # ── Geometry ──────────────────────────────────────────────────────────────

    def Length(self) -> float:
        return _math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def SqrLength(self) -> float:
        return self.x * self.x + self.y * self.y + self.z * self.z

    def Dot(self, other: "TGPoint3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def Cross(self, other: "TGPoint3") -> "TGPoint3":
        return TGPoint3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def UnitCross(self, other: "TGPoint3") -> "TGPoint3":
        v = self.Cross(other)
        v.Unitize()
        return v

    def Scale(self, factor: float) -> None:
        """In-place scalar multiply (matches NiPoint3.Scale in the Appc interface)."""
        self.x *= factor
        self.y *= factor
        self.z *= factor

    def Add(self, other: "TGPoint3") -> None:
        """In-place vector add (matches NiPoint3.Add in the Appc interface)."""
        self.x += other.x
        self.y += other.y
        self.z += other.z

    def Subtract(self, other: "TGPoint3") -> None:
        """In-place vector subtract (matches NiPoint3.Subtract in the Appc interface)."""
        self.x -= other.x
        self.y -= other.y
        self.z -= other.z

    def Set(self, other: "TGPoint3") -> None:
        """Copy XYZ from another TGPoint3 (in-place assignment)."""
        self.x = other.x
        self.y = other.y
        self.z = other.z

    def MultMatrixLeft(self, matrix: "TGMatrix3") -> None:
        """In-place transform by matrix: self = matrix · self (column-vector).

        Matches SDK NiPoint3.MultMatrixLeft semantics. Returns None.
        """
        x = matrix.m00 * self.x + matrix.m01 * self.y + matrix.m02 * self.z
        y = matrix.m10 * self.x + matrix.m11 * self.y + matrix.m12 * self.z
        z = matrix.m20 * self.x + matrix.m21 * self.y + matrix.m22 * self.z
        self.x = x
        self.y = y
        self.z = z

    def Unitize(self) -> float:
        """In-place normalize; return the length BEFORE normalization.

        Matches NiPoint3.Unitize() in the native Appc interface — SDK
        callers rely on `fLen = vDir.Unitize()` to extract distance while
        also unitizing the vector. Returns 0.0 for the zero-vector case
        (vector left unchanged)."""
        n = self.Length()
        if n > 1e-12:
            self.x /= n
            self.y /= n
            self.z /= n
        return n

    def GetPerpendicularComponent(self, axis: "TGPoint3") -> "TGPoint3":
        """The part of this vector at right angles to `axis`: ``v - (v·â)â``.

        Real Appc surface (App.py:3402). Returns a NEW vector — SWIG marks the
        result `thisown`, and BridgeHandlers.py:455 depends on it, Unitize()ing
        the result while continuing to use the original camera forward.

        The axis is used for its DIRECTION only, so its magnitude must not
        change the answer: AvoidObstacles.CalculateDirectionAppeal
        (AI/Preprocessors.py:1976) passes another ship's raw velocity in, and
        scaling by that ship's speed would skew every escape-direction score. A
        zero axis (a stationary obstacle, which that same call site hits
        routinely) projects out nothing and returns a copy rather than dividing
        by zero inside the AI tick.
        """
        n2 = axis.x * axis.x + axis.y * axis.y + axis.z * axis.z
        if n2 <= 1e-24:
            return TGPoint3(self.x, self.y, self.z)
        k = (self.x * axis.x + self.y * axis.y + self.z * axis.z) / n2
        return TGPoint3(self.x - k * axis.x,
                        self.y - k * axis.y,
                        self.z - k * axis.z)

    # ── Arithmetic ────────────────────────────────────────────────────────────

    def __add__(self, other: "TGPoint3") -> "TGPoint3":
        return TGPoint3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "TGPoint3") -> "TGPoint3":
        return TGPoint3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, s: float) -> "TGPoint3":
        return TGPoint3(self.x * s, self.y * s, self.z * s)

    def __rmul__(self, s: float) -> "TGPoint3":
        return TGPoint3(self.x * s, self.y * s, self.z * s)

    def __neg__(self) -> "TGPoint3":
        return TGPoint3(-self.x, -self.y, -self.z)

    def __eq__(self, other) -> bool:
        if not isinstance(other, TGPoint3):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __repr__(self) -> str:
        return f"TGPoint3({self.x}, {self.y}, {self.z})"


class TGMatrix3:
    """3×3 matrix stored row-major as nine slotted floats. Default is identity.

    Flat slotted storage, not a list-of-lists: the old form cost ~6
    allocations per instance (object + __dict__ + outer list + three rows),
    and ObjectClass.GetWorldRotation constructs one on every call at 70 call
    sites, per object, per frame.

    Naming: mIJ is row I, column J. Column-vector convention (CLAUDE.md ↦
    "Rotation matrix convention"), so GetCol(1) is forward.
    """

    __slots__ = ("m00", "m01", "m02", "m10", "m11", "m12", "m20", "m21", "m22")

    def __init__(self):
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0

    # ── Bulk access (used by the transform store) ─────────────────────────────

    def as_tuple(self) -> tuple:
        """Nine floats, row-major."""
        return (self.m00, self.m01, self.m02,
                self.m10, self.m11, self.m12,
                self.m20, self.m21, self.m22)

    def set_from_tuple(self, t) -> None:
        """Set all nine entries from a row-major sequence of nine floats."""
        (self.m00, self.m01, self.m02,
         self.m10, self.m11, self.m12,
         self.m20, self.m21, self.m22) = (
            float(t[0]), float(t[1]), float(t[2]),
            float(t[3]), float(t[4]), float(t[5]),
            float(t[6]), float(t[7]), float(t[8]))

    # ── Construction ──────────────────────────────────────────────────────────

    def MakeIdentity(self) -> "TGMatrix3":
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0
        return self

    def MakeZero(self) -> "TGMatrix3":
        self.m00 = 0.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = 0.0; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 0.0
        return self

    def MakeXRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = 1.0; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = c;   self.m12 = -s
        self.m20 = 0.0; self.m21 = s;   self.m22 = c
        return self

    def MakeYRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = c;   self.m01 = 0.0; self.m02 = s
        self.m10 = 0.0; self.m11 = 1.0; self.m12 = 0.0
        self.m20 = -s;  self.m21 = 0.0; self.m22 = c
        return self

    def MakeZRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self.m00 = c;   self.m01 = -s;  self.m02 = 0.0
        self.m10 = s;   self.m11 = c;   self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = 1.0
        return self

    def MakeRotation(self, angle: float, axis: TGPoint3) -> "TGMatrix3":
        """Rodrigues' rotation formula."""
        c, s = _math.cos(angle), _math.sin(angle)
        t = 1.0 - c
        x, y, z = axis.x, axis.y, axis.z
        self.m00 = t*x*x + c;   self.m01 = t*x*y - s*z; self.m02 = t*x*z + s*y
        self.m10 = t*x*y + s*z; self.m11 = t*y*y + c;   self.m12 = t*y*z - s*x
        self.m20 = t*x*z - s*y; self.m21 = t*y*z + s*x; self.m22 = t*z*z + c
        return self

    def MakeDiagonal(self, d: TGPoint3) -> "TGMatrix3":
        self.m00 = d.x; self.m01 = 0.0; self.m02 = 0.0
        self.m10 = 0.0; self.m11 = d.y; self.m12 = 0.0
        self.m20 = 0.0; self.m21 = 0.0; self.m22 = d.z
        return self

    # ── Row / Column / Entry access ───────────────────────────────────────────

    def GetRow(self, i: int) -> TGPoint3:
        if i == 0:
            return TGPoint3(self.m00, self.m01, self.m02)
        if i == 1:
            return TGPoint3(self.m10, self.m11, self.m12)
        if i == 2:
            return TGPoint3(self.m20, self.m21, self.m22)
        raise IndexError(i)

    def SetRow(self, i: int, v: TGPoint3) -> None:
        if i == 0:
            self.m00, self.m01, self.m02 = v.x, v.y, v.z
        elif i == 1:
            self.m10, self.m11, self.m12 = v.x, v.y, v.z
        elif i == 2:
            self.m20, self.m21, self.m22 = v.x, v.y, v.z
        else:
            raise IndexError(i)

    def GetCol(self, i: int) -> TGPoint3:
        if i == 0:
            return TGPoint3(self.m00, self.m10, self.m20)
        if i == 1:
            return TGPoint3(self.m01, self.m11, self.m21)
        if i == 2:
            return TGPoint3(self.m02, self.m12, self.m22)
        raise IndexError(i)

    def SetCol(self, i: int, v: TGPoint3) -> None:
        if i == 0:
            self.m00, self.m10, self.m20 = v.x, v.y, v.z
        elif i == 1:
            self.m01, self.m11, self.m21 = v.x, v.y, v.z
        elif i == 2:
            self.m02, self.m12, self.m22 = v.x, v.y, v.z
        else:
            raise IndexError(i)

    _ENTRY_NAMES = (("m00", "m01", "m02"),
                    ("m10", "m11", "m12"),
                    ("m20", "m21", "m22"))

    def GetEntry(self, i: int, j: int) -> float:
        return getattr(self, TGMatrix3._ENTRY_NAMES[i][j])

    def SetEntry(self, i: int, j: int, v: float) -> None:
        setattr(self, TGMatrix3._ENTRY_NAMES[i][j], float(v))

    def Set(self, *entries) -> None:
        """Set all 9 entries row-major: Set(m00,m01,m02, m10,m11,m12, m20,m21,m22)."""
        self.set_from_tuple(entries)

    # ── Operations ────────────────────────────────────────────────────────────

    def Transpose(self) -> "TGMatrix3":
        result = TGMatrix3()
        result.m00 = self.m00; result.m01 = self.m10; result.m02 = self.m20
        result.m10 = self.m01; result.m11 = self.m11; result.m12 = self.m21
        result.m20 = self.m02; result.m21 = self.m12; result.m22 = self.m22
        return result

    def MultMatrix(self, other: "TGMatrix3") -> "TGMatrix3":
        """self . other (column-vector convention).

        Unrolled. The triple `range(3)` loop this replaces ran 27 iterations,
        each doing five nested list-index operations, and allocated a matrix
        via MakeZero() only to overwrite every element — for a 3x3 multiply
        that is ~135 index ops and 27 interpreter loop steps.

        It is on the hot path: _integrate_rotation composes four of these per
        turning ship per tick (R_pitch . R_yaw . R_roll, then R . delta), which
        at 17 ships was the bulk of gl.motion's 10.4 ms.

        BIT-EXACT with the loop form, including the accumulation order (k
        ascending). Pinned by tests/unit/test_matrix_multiply_exact.py rather
        than argued: the only divergence the analysis admits is a signed zero,
        and a test is cheaper than being sure.
        """
        a00, a01, a02 = self.m00, self.m01, self.m02
        a10, a11, a12 = self.m10, self.m11, self.m12
        a20, a21, a22 = self.m20, self.m21, self.m22
        b00, b01, b02 = other.m00, other.m01, other.m02
        b10, b11, b12 = other.m10, other.m11, other.m12
        b20, b21, b22 = other.m20, other.m21, other.m22

        # The leading `0.0 +` is LOAD-BEARING, not noise. The loop form
        # accumulated into a MakeZero() element, i.e. ((0.0 + p0) + p1) + p2.
        # Dropping it gives (p0 + p1) + p2, which is identical for every input
        # except one: when all three products are -0.0, the accumulator yields
        # +0.0 and the bare sum yields -0.0. test_negative_zero_elements caught
        # exactly that on the first run. Nine extra adds is a trivial price for
        # not having to reason about whether a signed zero can reach a
        # rotation matrix.
        result = TGMatrix3()
        result.m00 = 0.0 + a00 * b00 + a01 * b10 + a02 * b20
        result.m01 = 0.0 + a00 * b01 + a01 * b11 + a02 * b21
        result.m02 = 0.0 + a00 * b02 + a01 * b12 + a02 * b22
        result.m10 = 0.0 + a10 * b00 + a11 * b10 + a12 * b20
        result.m11 = 0.0 + a10 * b01 + a11 * b11 + a12 * b21
        result.m12 = 0.0 + a10 * b02 + a11 * b12 + a12 * b22
        result.m20 = 0.0 + a20 * b00 + a21 * b10 + a22 * b20
        result.m21 = 0.0 + a20 * b01 + a21 * b11 + a22 * b21
        result.m22 = 0.0 + a20 * b02 + a21 * b12 + a22 * b22
        return result

    def MultMatrixLeft(self, other: "TGMatrix3") -> "TGMatrix3":
        return other.MultMatrix(self)

    def TransposeTimes(self, other: "TGMatrix3") -> "TGMatrix3":
        return self.Transpose().MultMatrix(other)

    def Congruence(self, other: "TGMatrix3") -> "TGMatrix3":
        return other.MultMatrix(self).MultMatrix(other.Transpose())

    def Inverse(self) -> "TGMatrix3":
        """For orthogonal rotation matrices, inverse == transpose."""
        return self.Transpose()

    def Reorthogonalize(self) -> "TGMatrix3":
        """Gram-Schmidt on rows to correct floating-point drift."""
        r0 = self.GetRow(0); r0.Unitize(); self.SetRow(0, r0)
        r1 = self.GetRow(1)
        dot01 = r0.Dot(r1)
        r1 = TGPoint3(r1.x - dot01 * r0.x, r1.y - dot01 * r0.y, r1.z - dot01 * r0.z)
        r1.Unitize(); self.SetRow(1, r1)
        r2 = r0.Cross(r1); self.SetRow(2, r2)
        return self

    def MultPoint(self, v: TGPoint3) -> TGPoint3:
        """Apply matrix to column vector: result = M * v."""
        return TGPoint3(
            self.m00*v.x + self.m01*v.y + self.m02*v.z,
            self.m10*v.x + self.m11*v.y + self.m12*v.z,
            self.m20*v.x + self.m21*v.y + self.m22*v.z,
        )

    # ── Euler angle extraction (stubs — used by some SDK scripts) ─────────────

    def ToEulerAnglesXYZ(self, *args) -> bool: return True
    def ToEulerAnglesXZY(self, *args) -> bool: return True
    def ToEulerAnglesYXZ(self, *args) -> bool: return True
    def ToEulerAnglesYZX(self, *args) -> bool: return True
    def ToEulerAnglesZXY(self, *args) -> bool: return True
    def ToEulerAnglesZYX(self, *args) -> bool: return True
    def FromEulerAnglesXYZ(self, *args) -> bool: return True
    def FromEulerAnglesXZY(self, *args) -> bool: return True
    def FromEulerAnglesYXZ(self, *args) -> bool: return True
    def FromEulerAnglesYZX(self, *args) -> bool: return True
    def FromEulerAnglesZXY(self, *args) -> bool: return True
    def FromEulerAnglesZYX(self, *args) -> bool: return True
    def ExtractAngleAndAxis(self, *args) -> None: pass
    def EigenSolveSymmetric(self, *args) -> None: pass

    def __eq__(self, other) -> bool:
        if not isinstance(other, TGMatrix3):
            return NotImplemented
        return self.as_tuple() == other.as_tuple()

    def __repr__(self) -> str:
        return f"TGMatrix3({self.as_tuple()})"


# ── Model-space direction constants ───────────────────────────────────────────
# BC uses Y-forward, Z-up convention (verified from placement file forward vectors
# that have dominant XY components with Z ≈ 0, and up vectors with dominant Z).

def TGPoint3_GetModelForward() -> TGPoint3:
    return TGPoint3(0.0, 1.0, 0.0)

def TGPoint3_GetModelBackward() -> TGPoint3:
    return TGPoint3(0.0, -1.0, 0.0)

def TGPoint3_GetModelUp() -> TGPoint3:
    return TGPoint3(0.0, 0.0, 1.0)

def TGPoint3_GetModelDown() -> TGPoint3:
    return TGPoint3(0.0, 0.0, -1.0)

def TGPoint3_GetModelRight() -> TGPoint3:
    return TGPoint3(1.0, 0.0, 0.0)

def TGPoint3_GetModelLeft() -> TGPoint3:
    return TGPoint3(-1.0, 0.0, 0.0)
