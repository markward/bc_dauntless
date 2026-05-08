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

Phase 1 fallback: TGL files are a binary format (uint32 offset table + ASCII
keys + UTF-16LE values) whose full structure isn't yet decoded.  GetString
returns the lookup key when no decoded entry is present, which keeps callers
operating on real strings (FindMenu("Helm"), TextBanner(..., "Friendly Fire"),
etc.) without crashing.  HasString reflects the actual cache contents.
"""


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
    def __init__(self, filename: str):
        self._filename = filename
        self._strings: dict[str, str] = {}
        self._sounds:  dict[str, str] = {}

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
        db = TGLocalizationDatabase(filename)
        self._cache[filename] = [db, 1]
        return db

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
