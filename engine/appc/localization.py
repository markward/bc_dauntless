"""TGLocalizationManager and TGLocalizationDatabase.

SDK call sites (MissionLib.py, UKConfig.py, loadsplash.py) follow the pattern:

    pDatabase = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    text = pDatabase.GetString("Helm")
    has  = pDatabase.HasString("Cloak")
    wav  = pDatabase.GetFilename("OpenCaptain05")
    App.g_kLocalizationManager.Unload(pDatabase)

The manager is reference-counted: the same filename loaded twice returns the
same database, and the database is released when refcount returns to zero.
This matches the Appc semantics — MissionLib.py routinely wraps Load/Unload
around short-lived menu queries on shared menu databases.

Load() resolves the SDK-relative path against game/ (real install) then
sdk/Build/ (SDK fallback) and decodes the binary TGL via
engine.missions.tgl_reader.  When the file can't be located, an empty
database is returned and GetString falls back to returning the key, which
keeps SDK call sites (FindMenu("Helm"), TextBanner(..., "Friendly Fire"),
etc.) operating on real strings rather than stubs.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_tgl_path(filename: str):
    """Resolve an SDK-form TGL path to a real file on disk, or None.

    SDK scripts pass paths like "data/TGL/Bridge Menus.tgl" — relative to
    the BC working directory. We mirror that by checking game/ first, then
    fall back to sdk/Build/ for SDK-shipped TGLs (used in headless tests
    where game/ may not be installed). The SDK ships its TGLs under
    sdk/Build/Data/TGL (capital D); the prefix is re-cased when present so
    lookups work on case-sensitive filesystems.
    """
    raw = Path(filename)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    candidates.append(_PROJECT_ROOT / "game" / filename)

    sdk_path = filename
    for lower in ("data/TGL/", "data/tgl/", "Data/tgl/"):
        if sdk_path.startswith(lower):
            sdk_path = "Data/TGL/" + sdk_path[len(lower):]
            break
    candidates.append(_PROJECT_ROOT / "sdk" / "Build" / sdk_path)
    candidates.append(_PROJECT_ROOT / filename)

    for c in candidates:
        if c.is_file():
            return c
    return None


def _tgstring_text(value) -> str:
    """Coerce any TGString-ish value to its plain Python text.

    Compare/CompareC accept str, _TGString (a str subclass), or a mutable
    TGString handle. The mutable TGString has no useful __str__, so extract
    its backing value explicitly; everything else is already str-compatible.
    """
    if isinstance(value, TGString):
        return value._value
    return str(value)


def _tgstring_compare(a_text: str, other, case_insensitive: int) -> int:
    """Shared C-strcmp comparison for both TGString classes.

    Real Appc binds TGString.Compare / TGString.CompareC (App.py:436-437) to
    strcmp-style routines: 0 when equal, <0 / >0 otherwise. Flag 1 requests a
    case-insensitive compare. SDK callers test ``not Compare(...)`` /
    ``Compare(...) == 0`` for a match, or ``Compare(...) != 0`` for difference.
    """
    a, b = a_text, _tgstring_text(other)
    if case_insensitive:
        a, b = a.lower(), b.lower()
    return (a > b) - (a < b)


class TGString:
    """Mutable TGString factory matching the SDK constructor idiom.

    SDK hardpoints do ``kS = App.TGString(); kS.SetString("0;Single;123;Dual")``
    then hand kS to a property setter. Distinct from _TGString (an immutable
    str subclass returned by localization lookups) because the SDK relies on
    SetString mutating an existing handle.
    """
    __slots__ = ("_value",)

    def __init__(self, value: str = ""):
        self._value = str(value)

    def SetString(self, value) -> None:
        self._value = str(value)

    def GetString(self) -> "_TGString":
        return _TGString(self._value)

    def GetCString(self) -> "_TGString":
        return _TGString(self._value)

    def GetLength(self) -> int:
        return len(self._value)

    def Compare(self, other, case_insensitive: int = 0) -> int:
        return _tgstring_compare(self._value, other, case_insensitive)

    def CompareC(self, other, case_insensitive: int = 0) -> int:
        return _tgstring_compare(self._value, other, case_insensitive)

    def Append(self, other) -> "TGString":
        # Mutable handle: append in place and return self, matching the SDK
        # idiom kString = kString.Append(kString2).
        self._value += str(other)
        return self

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"<TGString {self._value!r}>"


class _TGString(str):
    """Python str that also satisfies the SDK TGString API.

    SDK call sites chain ``pDatabase.GetString("Helm").GetCString()`` to
    extract the underlying C string from a TGString wrapper.  Subclassing
    str means the value already works wherever a Python string is expected
    (concatenation, equality, formatting) while exposing the legacy methods
    that hardpoint and mission scripts call on it.
    """
    __slots__ = ()

    def GetCString(self) -> "_TGString":
        # Returned as _TGString (still a `str` subclass) so downstream format
        # operations like ``pcString % (score, kills)`` route through our
        # tolerant ``__mod__`` instead of the bare-str version.
        return self

    def GetString(self) -> "_TGString":
        return self

    def GetLength(self) -> int:
        return len(self)

    def Append(self, other) -> "_TGString":
        # _TGString is an immutable str subclass, so return a new instance with
        # the concatenated value. SDK call sites reassign the result
        # (kString = kString.Append(kString2)), so this matches their usage.
        return _TGString(str(self) + str(other))

    def Compare(self, other, case_insensitive: int = 0) -> int:
        return _tgstring_compare(str(self), other, case_insensitive)

    def CompareC(self, other, case_insensitive: int = 0) -> int:
        return _tgstring_compare(str(self), other, case_insensitive)

    def __mod__(self, args) -> "_TGString":
        # Phase 1 fallback strings (key-as-value) don't carry %s placeholders
        # that real TGL values would, so SDK code like
        #   pDatabase.GetString("Your Stats").GetCString() % (score, kills)
        # raises TypeError on the unsubstituted key.  Absorb the mismatch and
        # return self — the headless engine doesn't render the text anyway.
        try:
            return _TGString(str.__mod__(self, args))
        except TypeError:
            return self


class TGLocalizationDatabase:
    def __init__(self, filename: str, *, strings=None, sounds=None):
        self._filename = filename
        self._strings: dict[str, str] = dict(strings) if strings else {}
        self._sounds:  dict[str, str] = dict(sounds) if sounds else {}

    def GetString(self, key: str) -> _TGString:
        # Headless fallback: return the key itself so consumers receive a
        # real string rather than a stub.  When the TGL parser lands in
        # Phase 2 the populated _strings table takes precedence.
        return _TGString(self._strings.get(key, key))

    def HasString(self, key: str) -> bool:
        return key in self._strings

    def GetFilename(self, key: str) -> str:
        # Sound-key lookups (OpenCaptain05.wav etc).  Empty string when
        # the key isn't registered — matches Appc behaviour for missing keys.
        return self._sounds.get(key, "")

    def GetSourceFilename(self) -> str:
        return self._filename

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<TGLocalizationDatabase {self._filename!r}>"


class TGLocalizationManager:
    def __init__(self):
        self._cache: dict[str, list] = {}  # filename -> [database, refcount]

    def Load(self, filename: str) -> TGLocalizationDatabase:
        entry = self._cache.get(filename)
        if entry is not None:
            entry[1] += 1
            return entry[0]
        db = self._build_database(filename)
        self._cache[filename] = [db, 1]
        return db

    @staticmethod
    def _build_database(filename: str) -> TGLocalizationDatabase:
        path = _resolve_tgl_path(filename)
        if path is None:
            return TGLocalizationDatabase(filename)
        # Lazy import — engine.missions.tgl_reader has no engine.appc deps,
        # but keeping the import inside the call keeps module-load time
        # minimal for tests that never touch localization data.
        from engine.missions.tgl_reader import read_tgl, TGLParseError
        try:
            parsed = read_tgl(path)
        except (TGLParseError, OSError):
            return TGLocalizationDatabase(filename)
        return TGLocalizationDatabase(
            filename, strings=parsed.strings, sounds=parsed.sounds)

    def Unload(self, database: TGLocalizationDatabase) -> None:
        for filename, entry in list(self._cache.items()):
            if entry[0] is database:
                entry[1] -= 1
                if entry[1] <= 0:
                    del self._cache[filename]
                return

    def GetIfRegistered(self, filename: str) -> "TGLocalizationDatabase | None":
        entry = self._cache.get(filename)
        return entry[0] if entry is not None else None

    def RegisterDatabase(self, database: TGLocalizationDatabase) -> None:
        # SDK compatibility: a database constructed externally can be inserted
        # into the manager so subsequent Load() calls return it.
        self._cache[database.GetSourceFilename()] = [database, 1]

    def DeleteAll(self) -> None:
        self._cache.clear()

    def Purge(self) -> None:
        # In Appc this releases unreferenced databases.  Headless behaviour:
        # drop entries whose refcount fell to zero (defensive — Unload should
        # already remove them).
        self._cache = {f: e for f, e in self._cache.items() if e[1] > 0}
