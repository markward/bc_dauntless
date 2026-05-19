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
        x = matrix._m[0][0] * self.x + matrix._m[0][1] * self.y + matrix._m[0][2] * self.z
        y = matrix._m[1][0] * self.x + matrix._m[1][1] * self.y + matrix._m[1][2] * self.z
        z = matrix._m[2][0] * self.x + matrix._m[2][1] * self.y + matrix._m[2][2] * self.z
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
    """3×3 matrix stored row-major. Default is identity."""

    def __init__(self):
        self._m: list[list[float]] = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]

    # ── Construction ──────────────────────────────────────────────────────────

    def MakeIdentity(self) -> "TGMatrix3":
        self._m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        return self

    def MakeZero(self) -> "TGMatrix3":
        self._m = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        return self

    def MakeXRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self._m = [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
        return self

    def MakeYRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self._m = [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
        return self

    def MakeZRotation(self, angle: float) -> "TGMatrix3":
        c, s = _math.cos(angle), _math.sin(angle)
        self._m = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
        return self

    def MakeRotation(self, angle: float, axis: TGPoint3) -> "TGMatrix3":
        """Rodrigues' rotation formula."""
        c, s = _math.cos(angle), _math.sin(angle)
        t = 1.0 - c
        x, y, z = axis.x, axis.y, axis.z
        self._m = [
            [t*x*x + c,     t*x*y - s*z, t*x*z + s*y],
            [t*x*y + s*z,   t*y*y + c,   t*y*z - s*x],
            [t*x*z - s*y,   t*y*z + s*x, t*z*z + c  ],
        ]
        return self

    def MakeDiagonal(self, d: TGPoint3) -> "TGMatrix3":
        self._m = [[d.x, 0.0, 0.0], [0.0, d.y, 0.0], [0.0, 0.0, d.z]]
        return self

    # ── Row / Column / Entry access ───────────────────────────────────────────

    def GetRow(self, i: int) -> TGPoint3:
        return TGPoint3(*self._m[i])

    def SetRow(self, i: int, v: TGPoint3) -> None:
        self._m[i] = [v.x, v.y, v.z]

    def GetCol(self, i: int) -> TGPoint3:
        return TGPoint3(self._m[0][i], self._m[1][i], self._m[2][i])

    def SetCol(self, i: int, v: TGPoint3) -> None:
        self._m[0][i] = v.x
        self._m[1][i] = v.y
        self._m[2][i] = v.z

    def GetEntry(self, i: int, j: int) -> float:
        return self._m[i][j]

    def SetEntry(self, i: int, j: int, v: float) -> None:
        self._m[i][j] = float(v)

    def Set(self, *entries) -> None:
        """Set all 9 entries row-major: Set(m00,m01,m02, m10,m11,m12, m20,m21,m22)."""
        flat = list(entries)
        for i in range(3):
            for j in range(3):
                self._m[i][j] = float(flat[i * 3 + j])

    # ── Operations ────────────────────────────────────────────────────────────

    def Transpose(self) -> "TGMatrix3":
        result = TGMatrix3()
        for i in range(3):
            for j in range(3):
                result._m[i][j] = self._m[j][i]
        return result

    def MultMatrix(self, other: "TGMatrix3") -> "TGMatrix3":
        result = TGMatrix3()
        result.MakeZero()
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    result._m[i][j] += self._m[i][k] * other._m[k][j]
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
            self._m[0][0]*v.x + self._m[0][1]*v.y + self._m[0][2]*v.z,
            self._m[1][0]*v.x + self._m[1][1]*v.y + self._m[1][2]*v.z,
            self._m[2][0]*v.x + self._m[2][1]*v.y + self._m[2][2]*v.z,
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
        return self._m == other._m

    def __repr__(self) -> str:
        return f"TGMatrix3({self._m})"


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
