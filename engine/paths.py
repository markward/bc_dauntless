"""Where the player's Bridge Commander content lives — the single authority.

BC content is ONE root: the game install (models, textures, icons, sounds,
TGL string tables, and the stock scripts as the retail .pyc, lifted by
engine.stock_scripts). It does not have to live inside the project tree.
The game never reads the BC SDK (spec
docs/superpowers/specs/2026-11-11-no-sdk-runtime-design.md, decision 1): a
stale ``--sdk-dir``, ``DAUNTLESS_SDK_DIR`` or ``settings.json`` [paths].sdk
is ignored (the flag logs one line), and the developer SDK chain lives in
tools/dev_sdk.py.

HARD RULE — paths resolve at USE, never at import.
    No module in engine/ may bind a module-level name to a path from here.
    Resolving early enough for import-time constants to work would make the
    first-run picker impossible: it runs after CEF is up, so anything captured
    at import is already stale by the time the player chooses a folder.

Nothing outside this module may spell "game" or "sdk" as a path segment.
tests/unit/test_path_indirection.py enforces both halves.

Spec: docs/superpowers/specs/2026-09-05-bc-path-resolution-design.md

User-data half. Where Dauntless WRITES, as opposed to where BC content is read.
    Three modes, highest first: ``--data-dir`` / ``DAUNTLESS_DATA_DIR`` (one
    folder for everything), a packaged build (marker file
    ``dauntless-packaged.json`` beside the install: the OS per-user folders),
    else a checkout (PROJECT_ROOT, today's layout). Use ``config_dir``,
    ``saves_dir``, ``mods_default_dir``, ``cache_dir``, ``log_dir`` and
    ``log_file_path``; resolve at use, like the content roots. A write that
    fails goes through ``report_write_failure(path, exc)``, which names the
    path on stderr once per path instead of swallowing it.

Spec: docs/superpowers/specs/2026-10-16-per-user-data-dirs-design.md
"""
from __future__ import annotations

import ntpath
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine.core import case_paths

# The markers are paths the engine actually loads. The stock scripts are
# read from the install (engine.stock_scripts lifts its .pyc), so an install
# without its scripts folder cannot boot: scripts/MissionLib.pyc stands for
# it, and is matched case-insensitively (_CASE_BLIND_MARKERS), as the stock
# loader matches that folder. The full per-file proof is the boot install
# check (engine.stock_scripts.validate_install), not this marker list.
# stbc.exe is deliberately absent: it is never loaded.
GAME_MARKERS: tuple[str, ...] = (
    "data", "data/Models", "data/Textures", "data/Icons", "scripts/MissionLib.pyc")
_CASE_BLIND_MARKERS = frozenset({"scripts/MissionLib.pyc"})

_MARKERS = {"game": GAME_MARKERS}


@dataclass(frozen=True)
class Validation:
    """The verdict on one candidate root.

    `missing` lists the markers that were absent, in declaration order.
    `hint` is a specific diagnosis of a recognisable mistake, or None.
    """
    ok: bool
    root: Path
    missing: tuple[str, ...]
    hint: Optional[str]


def normalise(path) -> Path:
    """expanduser -> abspath -> normpath. Deliberately NOT Path.resolve().

    Symlinks are not followed: an install behind a symlink to an external
    volume keeps working across remounts, where a resolved target would not.
    """
    return Path(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


def _marker_present(root: Path, marker: str) -> bool:
    if (root / marker).exists():
        return True
    return marker in _CASE_BLIND_MARKERS and case_paths.resolve(root, marker) is not None


def _markers_ok(root: Path, markers: tuple[str, ...]) -> bool:
    return all(_marker_present(root, m) for m in markers)


def _case_insensitive_spelling(root: Path, rel: str) -> Optional[str]:
    """The real on-disk spelling of `rel` under `root`, matched case-blind.

    Returns None when no case-blind match exists. On a case-INSENSITIVE
    filesystem this is never reached, because the exact check already
    succeeded.
    """
    current = root
    found: list[str] = []
    for segment in rel.split("/"):
        try:
            entries = list(current.iterdir())
        except OSError:
            return None
        match = next((e for e in entries if e.name.lower() == segment.lower()), None)
        if match is None:
            return None
        found.append(match.name)
        current = match
    return "/".join(found)


def _hint_for(root: Path, kind: str, missing: tuple[str, ...]) -> Optional[str]:
    """Diagnose the mistakes a person actually makes. Order matters: the
    case hint is unambiguous when it fires, so it wins."""
    # Case only — every missing marker has a case-blind match on disk.
    spellings = {m: _case_insensitive_spelling(root, m) for m in missing}
    if missing and all(spellings.values()):
        m = missing[0]
        return f"found '{spellings[m]}', expected '{m}' — this volume is case-sensitive"

    # A content-only copy: every data marker is there, the scripts are not.
    # The old validator accepted these, so it is the likeliest upgrade case;
    # name the missing file (the first-run row shows only the hint).
    scripts_only = tuple(m for m in missing if m in _CASE_BLIND_MARKERS)
    if missing and scripts_only == missing:
        return (f"No Bridge Commander scripts here: {missing[0]} is missing. "
                "Pick the full game folder.")

    # The parent was picked: this folder CONTAINS a valid game/.
    child = root / kind
    if child.is_dir() and _markers_ok(child, _MARKERS[kind]):
        return f"That folder contains '{kind}' — did you mean {child}?"

    # One level too deep: the parent is the root that was wanted.
    parent = root.parent
    if parent != root and _markers_ok(parent, _MARKERS[kind]):
        return f"That's the {root.name} folder — pick its parent ({parent})."

    return None


def _validate(path, kind: str) -> Validation:
    # An empty value can never name a root, and must not be normalised
    # first: os.path.abspath("") is the CURRENT WORKING DIRECTORY, so an
    # empty --game-dir would validate against cwd and, launched from
    # inside a real BC install, silently succeed -- the precise failure
    # the set-but-invalid rule exists to prevent.
    if not str(path).strip():
        return Validation(ok=False, root=Path(""), missing=_MARKERS[kind],
                          hint="No path given — the flag or setting is present but empty.")
    root = normalise(path)
    markers = _MARKERS[kind]
    missing = tuple(m for m in markers if not _marker_present(root, m))
    if not missing:
        return Validation(ok=True, root=root, missing=(), hint=None)
    return Validation(ok=False, root=root, missing=missing,
                      hint=_hint_for(root, kind, missing))


def validate_game_root(path) -> Validation:
    """Is `path` a usable BC game install? One stat per marker, no writes.
    Markers only: the boot install check (engine.stock_scripts.
    validate_install) proves the stock scripts on top of this."""
    return _validate(path, "game")


# --- resolution -------------------------------------------------------------

# engine/paths.py -> engine/ -> <project root>. Kept as a module attribute
# rather than a local so tests can point the legacy fallback at a tmp_path.
# Path.resolve() here is fine -- the module's "never resolve()" rule protects
# a user-supplied BC root from having its symlinks followed; this locates
# OUR OWN module file, the same idiom engine/settings_store.py already uses.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CLI_FLAGS = {"game": "--game-dir"}
ENV_VARS = {"game": "DAUNTLESS_GAME_DIR"}
_PROJECT_DIR = {"game": "game"}
_VALIDATORS = {"game": validate_game_root}

# The game no longer reads the SDK. An old shortcut passing this flag still
# boots; the flag is reported once per process and otherwise ignored.
IGNORED_SDK_FLAG = "--sdk-dir"
_IGNORED_SDK_FLAG_LINE = ("[paths] --sdk-dir is no longer used: BC Dauntless "
                          "reads Bridge Commander's scripts from your game folder")
_sdk_flag_warned = False


class PathsUnresolved(RuntimeError):
    """No usable game root. Carries describe_failure()'s text.

    Not meant to be handled: it is a boot-time configuration error and the
    message is the whole point.
    """


def _only_game(kind: str) -> None:
    if kind != "game":
        raise ValueError(f"the game root is the only content root, not {kind!r}")


@dataclass(frozen=True)
class Resolution:
    """The outcome of one resolve(). `game` is set ONLY when valid.

    An invalid candidate leaves the root None and records the attempt in
    `game_validation`, so describe_failure() can name the path and say what
    was wrong with it. `source(kind)`/`validation(kind)` keep their `kind`
    parameter for the first-run screen's row vocabulary; "game" is the only
    kind.
    """
    game: Optional[Path]
    game_source: str            # "picker" | "cli" | "env" | "settings" | "project" | ""
    game_validation: Optional[Validation]

    @property
    def ok(self) -> bool:
        return self.game is not None

    def source(self, kind: str) -> str:
        _only_game(kind)
        return self.game_source

    def validation(self, kind: str) -> Optional[Validation]:
        _only_game(kind)
        return self.game_validation


# Distinguishes "flag absent" from "flag present with an empty value" --
# `None` and `""` are both falsy, so a plain Optional[str] return can't tell
# them apart. See _candidate()'s CLI tier for why the distinction matters.
_UNSET = object()


def _flag_value(argv, flag: str) -> str | object:
    """Support both `--game-dir X` and `--game-dir=X`.

    Returns `_UNSET` when the flag never appears in argv. Returns the raw
    value -- which may be `""` -- when it does. Callers must check `is
    _UNSET`, not truthiness: an explicit `--game-dir=` is a real answer
    (an empty one), not the absence of one.
    """
    for i, token in enumerate(argv):
        if token == flag:
            return argv[i + 1] if i + 1 < len(argv) else ""
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return _UNSET


def _candidate(kind: str, argv, env, store, picked=None):
    """The highest-precedence SET source for the root, as (value, source).

    Returns (None, "") when nothing is set. A set-but-wrong source is
    returned as-is and never skipped in favour of a lower one -- falling
    through would run a different install than the one that was asked for.

    "Set" is deliberately NOT the same test at every tier -- see each
    branch below for why.
    """
    # Picker: a folder the player chose in the first-run dialog, and the
    # most recent explicit human act there is. It outranks the CLI tier
    # BECAUSE of the set-wins rule, not in spite of it: an invalid
    # --game-dir stays "set", so anything lower would lose to the very
    # flag the dialog exists to correct.
    if picked is not None:
        chosen = picked.get(kind)
        if chosen is not None:
            return chosen, "picker"

    # CLI: present in argv -> SET, even when the value is "". Typing the
    # flag is an explicit act at launch (`--game-dir="$UNSET_VAR"` with the
    # shell var unset still puts `--game-dir=` on argv); treating that the
    # same as never having typed the flag would silently boot a different
    # install than the one the user named. Compare `is not _UNSET`, never
    # truthiness.
    flag = _flag_value(argv, CLI_FLAGS[kind])
    if flag is not _UNSET:
        return flag, "cli"

    # Env: present-but-empty is treated as UNSET -- deliberately asymmetric
    # with the CLI tier above. `FOO=${BAR:-}` is idiomatic shell for
    # "unset", and CI tooling routinely exports empty vars for undefined
    # ones; erroring here would break boots that should work, and (unlike
    # the CLI tier) an empty env value can't be the wrong-install harm the
    # SET-wins rule exists to prevent, because nobody deliberately exports
    # an empty override meaning "use THIS exact root".
    from_env = env.get(ENV_VARS[kind])
    if from_env:
        return from_env, "env"

    # settings.json: store.has() IS the SET check -- a present key means
    # set, full stop, regardless of its value. Don't re-check the retrieved
    # value's truthiness: persist() only ever writes valid non-empty paths,
    # so a present-but-empty stored value means a hand-edit, and that
    # deserves to be reported as an error, not silently skipped in favour
    # of the project default.
    if store is not None and store.has("paths", kind):
        return store.get("paths", kind), "settings"

    project = PROJECT_ROOT / _PROJECT_DIR[kind]
    if project.is_dir():
        return str(project), "project"

    return None, ""


def warn_ignored_sdk_sources(argv) -> None:
    """Say once per process, on stderr, that `--sdk-dir` is ignored, when
    `argv` carries it. An old shortcut must still boot (spec 2026-11-11
    §4.4); DAUNTLESS_SDK_DIR and settings.json [paths].sdk stay silent, as
    the developer SDK chain (tools/dev_sdk.py) still reads them."""
    global _sdk_flag_warned
    if _sdk_flag_warned or _flag_value(argv, IGNORED_SDK_FLAG) is _UNSET:
        return
    _sdk_flag_warned = True
    print(_IGNORED_SDK_FLAG_LINE, file=sys.stderr)


def resolve(argv=None, env=None, store=None, picked=None) -> Resolution:
    """Resolve the game root. PURE apart from warn_ignored_sdk_sources()'s
    one stderr line: no writes, no ambient state beyond the defaults for
    argv/env/store.

    `picked` is the first-run dialog's answer -- a dict keyed "game" -- and
    outranks every other source. It is a plain argument, not ambient
    state, so this function still never prompts and never blocks.

    settings_store is imported HERE rather than at module scope: it imports
    engine.ui.configuration_panel, and this module is imported by
    engine/audio/ and engine/appc/.
    """
    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    warn_ignored_sdk_sources(argv)

    value, source = _candidate("game", argv, env, store, picked)
    if value is None:
        return Resolution(game=None, game_source=source, game_validation=None)
    verdict = _VALIDATORS["game"](value)
    return Resolution(game=verdict.root if verdict.ok else None,
                      game_source=source, game_validation=verdict)


def persist(resolution: Resolution, store=None) -> None:
    """Write a CLI- or picker-sourced game root to settings.json [paths].

    Only these two sources, and only when valid. An env var is ephemeral by
    contract, so `DAUNTLESS_GAME_DIR=/fixtures pytest` cannot mutate a real
    config; and a typo never becomes the stored answer, which would make
    the NEXT launch fail for a reason the player has already forgotten
    about. A picked root is stored for the opposite reason: the whole
    point of asking was to not ask again. [paths].sdk is never written
    (the developer SDK chain owns it).
    """
    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    if resolution.game is not None and resolution.game_source in ("cli", "picker"):
        store.set("paths", "game", str(resolution.game))


# --- the cache --------------------------------------------------------------

_RESOLUTION: Optional[Resolution] = None


def configure(resolution: Optional[Resolution]) -> None:
    """Install a Resolution as the answer every accessor reads.

    Callable more than once, and later calls are observed by every consumer:
    that is what the first-run picker needs, and it is why nothing may capture
    a path at import. Pass None to clear (tests).
    """
    global _RESOLUTION
    _RESOLUTION = resolution


def current() -> Resolution:
    """The configured Resolution, resolving from ambient state if configure()
    has not run. The lazy path keeps a tools/ script or an isolated test
    working without a boot sequence."""
    global _RESOLUTION
    if _RESOLUTION is None:
        _RESOLUTION = resolve()
    return _RESOLUTION


def game_root() -> Path:
    """The BC game install root. Never captured at module scope."""
    resolution = current()
    if resolution.game is None:
        raise PathsUnresolved(describe_failure(resolution))
    return resolution.game


def stock_scripts() -> Path:
    """The install's own scripts folder (game_root()/scripts), matched
    case-insensitively. Resolved at use, never captured."""
    root = game_root()
    found = case_paths.resolve(root, "scripts")
    return found if found is not None else root / "scripts"


def game_asset(rel) -> Path:
    """Absolutise a BC-relative asset path, e.g. "data/Textures/x.tga".

    An installed mod that provides this path wins. Imported lazily, like
    settings_store in resolve(), so engine.mods can import engine.paths.

    The stock path is matched case-insensitively (engine.core.case_paths):
    BC content spells paths with whatever case it likes. A path that does
    not exist in any case comes back exactly as spelled, so callers that
    probe for optional files with .exists() still see it missing.
    """
    from engine import mods
    override = mods.game_override(rel)
    if override is not None:
        return override
    return _stock_game_path(rel)


def _stock_game_path(rel) -> Path:
    """`game_root() / rel`, with the on-disk spelling where only case differs."""
    root = game_root()
    return case_paths.resolve(root, str(rel)) or root / rel


PACKAGED_MARKER = "dauntless-packaged.json"
DATA_DIR_FLAG = "--data-dir"
DATA_DIR_ENV = "DAUNTLESS_DATA_DIR"


def is_packaged() -> bool:
    """True when the install folder carries the packaged-build marker."""
    return (PROJECT_ROOT / PACKAGED_MARKER).is_file()


class RepoWriteInPackagedBuild(OSError):
    """A developer authoring save targeted the install folder of a packaged
    build. An OSError so the panels' existing "Save failed" paths catch it."""


def refuse_repo_write_when_packaged(path) -> None:
    """Raise RepoWriteInPackagedBuild when `path` is inside the packaged
    install (resolved on both sides); a no-op in a source checkout."""
    if not is_packaged():
        return
    target = Path(path).resolve()
    if target.is_relative_to(PROJECT_ROOT.resolve()):
        raise RepoWriteInPackagedBuild(
            "%s is inside the Dauntless install; developer authoring saves "
            "need a source checkout" % path)


def data_dir_override(argv=None, env=None) -> Optional[Path]:
    """The user-data root asked for by `--data-dir` or DAUNTLESS_DATA_DIR.

    Flag first, then env. An empty value counts as unset (unlike the game
    flag, an empty data dir has no meaning to correct). Read on every call.
    """
    if argv is None:
        argv = sys.argv[1:]
    if env is None:
        env = os.environ
    flag = _flag_value(argv, DATA_DIR_FLAG)
    if flag is not _UNSET and str(flag).strip():
        return normalise(flag)
    from_env = env.get(DATA_DIR_ENV)
    if from_env and from_env.strip():
        return normalise(from_env)
    return None


def data_layout() -> tuple[str, Optional[Path]]:
    """("override", root) | ("packaged", None) | ("checkout", PROJECT_ROOT)."""
    override = data_dir_override()
    if override is not None:
        return ("override", override)
    if is_packaged():
        return ("packaged", None)
    return ("checkout", PROJECT_ROOT)


def _checkout_root() -> Optional[Path]:
    """The root of the checkout-style layout, or None when packaged."""
    return data_layout()[1]


def config_dir() -> Path:
    root = _checkout_root()
    return root if root is not None else os_user_dirs()["config"]


def saves_dir() -> Path:
    root = _checkout_root()
    return root / "saves" if root is not None else os_user_dirs()["saves"]


def mods_default_dir() -> Path:
    root = _checkout_root()
    return root / "mods" if root is not None else os_user_dirs()["mods"]


def cache_dir() -> Path:
    root = _checkout_root()
    return root / "cache" if root is not None else os_user_dirs()["cache"]


def log_dir() -> Path:
    root = _checkout_root()
    return root if root is not None else os_user_dirs()["logs"]


def log_file_path() -> Path:
    root = _checkout_root()
    if root is not None:
        return root / "logs" / "dauntless.log"
    return os_user_dirs()["logs"] / "dauntless.log"


def structure_parts_cache_root() -> Path:
    """Where hull structure-part segmentations (.sps files, layered damage
    phase 4 §2.2) are cached: <cache_dir()>/structure_parts. Computed fresh
    on every call; callers must never capture the result at import.
    """
    return cache_dir() / "structure_parts"


_reported_write_failures: set[str] = set()


def _reset_write_failure_reports() -> None:
    """Forget which paths were reported (tests)."""
    _reported_write_failures.clear()


def report_write_failure(path, exc: BaseException) -> None:
    """Say once per path per process that a user-data write failed.

    Always prints to stderr, with or without --developer: a player whose
    saves silently vanish needs to see why. Never raises.
    """
    try:
        key = str(path)
        if key in _reported_write_failures:
            return
        _reported_write_failures.add(key)
        print("[dauntless] could not write %s: %s: %s"
              % (key, type(exc).__name__, exc), file=sys.stderr)
    except Exception:
        pass


def project_asset_root() -> Path:
    """Where PROJECT-authored renderer assets live -- <PROJECT_ROOT>/native/
    assets (the collision-scuff normal map under textures/, the CEF UI under
    ui-cef/). Distinct from game_root(): BC content is the player's install,
    this is ours. Computed fresh on every call, like structure_parts_cache_root().
    """
    return PROJECT_ROOT / "native" / "assets"


# --- per-user OS folders ----------------------------------------------------

def _windows_known_folder(name: str) -> Optional[Path]:
    """SHGetKnownFolderPath for "RoamingAppData" / "LocalAppData", or None on
    any failure. Windows only; never called elsewhere."""
    try:
        import ctypes
        from ctypes import wintypes
        guids = {
            "RoamingAppData": "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}",
            "LocalAppData": "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}",
        }
        import uuid
        u = uuid.UUID(guids[name])

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        guid = _GUID(u.time_low, u.time_mid, u.time_hi_version,
                     (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        out = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
                       ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(guid), 0, None, ctypes.byref(out)) != 0 or not out.value:
            return None
        try:
            return Path(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        return None


def os_user_dirs(platform: Optional[str] = None,
                 env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None,
                 known_folder: Optional[Callable[[str], Optional[Path]]] = None
                 ) -> dict[str, Path]:
    """Where the per-OS user folders live: config, saves, mods, cache, logs.

    Pure apart from its defaults (sys.platform, os.environ, Path.home(),
    the Windows known-folder API). Computed fresh per call; callers must
    never capture the result at import. An XDG_* / APPDATA value that is
    unset, empty or relative is ignored.
    """
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home

    if platform == "win32":
        kf = known_folder if known_folder is not None else _windows_known_folder

        def _win(folder: str, var: str, fallback: str) -> Path:
            got = kf(folder)
            if got is not None:
                return Path(got)
            val = env.get(var, "")
            if val and ntpath.isabs(val):
                return Path(val)
            return home / "AppData" / fallback

        roaming = _win("RoamingAppData", "APPDATA", "Roaming")
        local = _win("LocalAppData", "LOCALAPPDATA", "Local")
        config = roaming / "Dauntless"
        return {"config": config, "saves": config / "saves",
                "mods": config / "mods",
                "cache": local / "Dauntless" / "Cache",
                "logs": local / "Dauntless" / "Logs"}

    if platform == "darwin":
        lib = home / "Library"
        config = lib / "Application Support" / "Dauntless"
        return {"config": config, "saves": config / "saves",
                "mods": config / "mods",
                "cache": lib / "Caches" / "Dauntless",
                "logs": lib / "Logs" / "Dauntless"}

    def _xdg(var: str, default: Path) -> Path:
        val = env.get(var, "")
        if val and os.path.isabs(val):
            return Path(val)
        return default

    cfg = _xdg("XDG_CONFIG_HOME", home / ".config")
    data = _xdg("XDG_DATA_HOME", home / ".local" / "share")
    cache = _xdg("XDG_CACHE_HOME", home / ".cache")
    state = _xdg("XDG_STATE_HOME", home / ".local" / "state")
    return {"config": cfg / "dauntless",
            "saves": data / "dauntless" / "saves",
            "mods": data / "dauntless" / "mods",
            "cache": cache / "dauntless",
            "logs": state / "dauntless" / "logs"}


def game_asset_dirs(rel) -> list:
    """Every directory to SEARCH for `rel`, mod directories first.

    game_asset() answers "which file?", which a caller that scans a
    directory cannot use. Always includes the stock directory last, so a
    modless call is exactly today's single-directory behaviour wrapped in a
    list.
    """
    from engine import mods
    return [*mods.replacements().dirs_for(rel), *mods.current().dirs_for(rel),
            _stock_game_path(rel)]


# --- the failure message ----------------------------------------------------

def describe_failure(resolution: Resolution) -> str:
    """Every source consulted and what each said. Empty when nothing failed."""
    if resolution.ok:
        return ""

    kind, label = "game", "game folder"
    lines = ["dauntless: cannot locate your Bridge Commander install.", ""]
    verdict = resolution.game_validation
    if verdict is None:
        lines.append(f"  {label}: not found")
        lines.append(f"     {CLI_FLAGS[kind]:<18}(not given)")
        lines.append(f"     {ENV_VARS[kind]:<18}(not set)")
        lines.append(f"     {'settings.json':<18}(not set)")
        project = PROJECT_ROOT / _PROJECT_DIR[kind]
        lines.append(f"     {str(project):<18}(does not exist)")
    else:
        # _validate's empty-value guard sets root=Path(""), which
        # stringifies to "." -- printing that verbatim reads as a
        # reference to cwd, exactly the confusion the guard exists to
        # avoid. Name it plainly instead.
        root_display = "(empty)" if verdict.root == Path("") else str(verdict.root)
        lines.append(f"  {label}: invalid — {root_display}")
        lines.append(f"     missing: {', '.join(verdict.missing)}")
        lines.append(f"     source : {resolution.game_source}")
        if verdict.hint:
            lines.append(f"     hint   : {verdict.hint}")
    lines.append("")

    lines += [
        "Set it once and it persists:",
        "",
        '  ./build/dauntless --game-dir "/path/to/Star Trek Bridge Commander/game"',
        "",
    ]
    return "\n".join(lines)
