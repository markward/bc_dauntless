# Developer Flag — Design

**Status:** Draft, pre-implementation.
**Sub-project:** Runtime `--developer` CLI flag gating dev-only UI,
keybindings, and behaviour overrides across the C++ host, the Python
host loop, and the CEF UI overlay.

## Why this scope

Debug shortcuts and inspectors are added and removed by hand from
`engine/host_loop.py` repeatedly (e.g. the F10 shield-debug binding at
`host_loop.py:2419`). The current pattern has three problems:

1. Each new debug surface requires editing the central host-loop switch
   and removing it again before the change is shared.
2. There is no consistent way to mark a UI element (pause-menu entry,
   HUD overlay, renderer wireframe) as "developer only" so it stays
   visible during normal play unless explicitly hidden.
3. Temporary game-behaviour overrides (e.g. invulnerability for testing
   AI, scripted-event force-fires) have no obvious switch — they get
   commented in/out by hand and occasionally ship.

A single runtime flag, `--developer`, fixes this by giving every tier
of the stack a cheap, direct way to ask "are we in dev mode?" and by
providing small Python helpers so adding a dev-only keybinding or
behaviour override is a one-liner.

## Goals

1. Single source of truth for "is this a developer session?" parsed
   once from `argv` in the C++ host.
2. Direct, ergonomic access from each tier:
   - C++ renderer: `dauntless::is_developer_mode()` (header-level
     `bool` getter).
   - Python host loop and engine modules: `engine.dev_mode.is_enabled()`.
   - CEF JS/HTML: `window.__DAUNTLESS_DEV__` (boolean global) and
     `document.body.dataset.dev === "1"` for CSS-driven hide/show.
3. Python helpers that make the common cases trivial:
   - `register_dev_keybinding(key, handler, description)` — keybindings
     registered through this call are dispatched only when dev mode is
     on, and are skipped silently otherwise.
   - `dev_only(fn)` decorator — wraps a callable so it executes only in
     dev mode (returns `None` otherwise). Used for behaviour overrides.
4. CEF pause menu gains a dev-only section visible only under
   `--developer`. New dev panels and the future developer console live
   in the same dev-only DOM region.
5. Default off: no `--developer` means no observable change to the
   normal play surface.

## Non-goals

- Compile-time stripping of dev code. The flag is purely runtime; the
  same binary serves both modes. (See "Alternatives considered".)
- Sub-flags such as `--developer --dev-cheat=invuln`. The flag is a
  single boolean for now; richer dev configuration can layer on later
  by parsing additional args in the same place.
- Persisting the flag across launches via `Options.cfg`. Each launch
  reads `argv` only. A workstation-local default would be a future
  follow-up if desired.
- Migrating every existing scattered debug keybinding in one go. The
  existing F10 shield-debug binding moves behind the new registry as
  part of this change; other ad-hoc debug surfaces migrate
  opportunistically.

## Architecture

The flag is parsed once in C++ and exposed by each tier in its
idiomatic way. There is one truth bit (in C++), three read APIs (one
per tier), and one push event (Python → CEF) that propagates the bit
across the process boundary into the browser.

### C++ host

- `host_main.cc` (after the existing `--smoke-check` / `--banner`
  branches) scans `argv` for a `--developer` token and sets a
  module-local `bool g_developer_mode`.
- A new header, e.g. `native/src/host/developer_mode.h`, exports
  `namespace dauntless { bool is_developer_mode(); }` backed by
  `developer_mode.cc` returning the bool.
- The same bool is exposed on the embed module as
  `_dauntless_host.developer_mode` (read-only attribute set during the
  pybind11 module init in `native/src/host/host_bindings.cc`, after
  argv has been parsed).
- The renderer reads the getter directly when it needs to draw
  dev-only overlays.

### Python — `engine/dev_mode.py`

A new tiny module owning the Python-side surface:

```python
# engine/dev_mode.py
import _dauntless_host

def is_enabled() -> bool:
    return bool(getattr(_dauntless_host, "developer_mode", False))

_dev_keybindings: dict[int, tuple[Callable, str]] = {}

def register_dev_keybinding(key: int, handler: Callable, description: str) -> None:
    """Register a keybinding that fires only when --developer is set."""
    _dev_keybindings[key] = (handler, description)

def dispatch_dev_key(key: int) -> bool:
    """Called from the host-loop input dispatch. Returns True if handled."""
    if not is_enabled():
        return False
    entry = _dev_keybindings.get(key)
    if entry is None:
        return False
    entry[0]()
    return True

def dev_only(fn):
    """Decorator: callable runs only in dev mode, else returns None."""
    def wrapper(*args, **kwargs):
        if not is_enabled():
            return None
        return fn(*args, **kwargs)
    return wrapper

def keybinding_descriptions() -> list[tuple[int, str]]:
    """For the dev pause-menu section to list active dev shortcuts."""
    return sorted((k, desc) for k, (_, desc) in _dev_keybindings.items())
```

The host loop's input dispatch calls `dev_mode.dispatch_dev_key(key)`
before falling through to normal handling. The existing F10
shield-debug binding moves into `engine/dev_keybindings.py` (a new
module that does the registration on import) so it's no longer in the
host-loop switch.

### CEF UI

- After CEF finishes the initial document load (existing pattern at
  `cef_lifecycle.cc:138`-ish), the Python host loop calls
  `ExecuteJavaScript(...)` with:
  ```js
  window.__DAUNTLESS_DEV__ = true;
  document.body.dataset.dev = "1";
  ```
  if and only if `dev_mode.is_enabled()` is true. When off, neither
  the global nor the data attribute is set, so the default state of
  the HTML is "production".
- The pause-menu HTML in `native/assets/ui-cef/hello.html` gains a
  `<section class="dev-only" id="pause-menu-dev">` block with the
  dev-only entries. CSS in the same file:
  ```css
  .dev-only { display: none; }
  body[data-dev="1"] .dev-only { display: block; }
  ```
- Future dev panels (renderer-state inspector, scripted-event force
  panel, developer console) live in DOM nodes carrying the `dev-only`
  class. No JS-level visibility plumbing required.

### Data flow

```
argv[1..] ──parse──► g_developer_mode (C++ bool)
                       │
                       ├──► dauntless::is_developer_mode()   ◄── native renderer
                       │
                       └──► _dauntless_host.developer_mode   ◄── engine.dev_mode
                                                                    │
                                                                    └──► host_loop, at CEF init:
                                                                         ExecuteJavaScript("window.__DAUNTLESS_DEV__ = true; document.body.dataset.dev='1'")
                                                                                                    │
                                                                                                    ▼
                                                                                       CEF DOM ── CSS reveals .dev-only
```

## Components

| Component | Lives in | Responsibility |
|---|---|---|
| Argv parsing | `native/src/host/host_main.cc` | One-line scan for `--developer`; sets `g_developer_mode`. |
| C++ getter | `native/src/host/developer_mode.{h,cc}` | `dauntless::is_developer_mode()`. |
| Embed module attr | `native/src/host/host_bindings.cc` | Sets `_dauntless_host.developer_mode` from the getter at pybind11 module init. |
| Python facade | `engine/dev_mode.py` | `is_enabled()`, registry, decorator, dispatch helper. |
| Dev keybindings | `engine/dev_keybindings.py` | Imports `dev_mode` and registers the existing F10 shield-debug handler (plus any new ones added behind the flag). |
| Host-loop hook | `engine/host_loop.py` (input dispatch + CEF init) | Calls `dev_mode.dispatch_dev_key(key)`; pushes the JS init string at CEF startup. |
| CEF DOM | `native/assets/ui-cef/hello.html` | `.dev-only` CSS rule; `pause-menu-dev` section; future dev panels. |

## Error handling

- If `_dauntless_host` does not expose `developer_mode` (e.g. a stale
  `.so` against a new Python module), `engine.dev_mode.is_enabled()`
  returns `False` via the `getattr(..., False)` fallback. The game
  runs as if `--developer` were not passed, which is the safe default.
  Per CLAUDE.md's stale-binary guidance, this manifests as "dev
  features inert despite the flag" — the fix is to rebuild
  `build/dauntless`, not to add a Python-side workaround.
- An unknown `argv[1]` (e.g. `--develper` typo) falls through the
  existing `host_main.cc` mode switch as before; no new error path is
  introduced. The flag is positional-agnostic — the scan looks at all
  argv slots after `argv[0]` so it composes with the existing
  `--smoke-check` / `--banner` modes if a developer wants both.
- The `ExecuteJavaScript` push to CEF happens at most once per CEF
  document load. If the document reloads, the host loop re-pushes.
  CSS hides `.dev-only` by default, so a missing push fails closed (no
  dev UI shown) rather than open.

## Testing

- **Unit**: `tests/engine/test_dev_mode.py` covers
  `register_dev_keybinding` + `dispatch_dev_key` (returns False when
  disabled; calls handler and returns True when enabled), and the
  `dev_only` decorator (no-op when disabled, calls through when
  enabled). The flag itself is monkey-patched via
  `_dauntless_host.developer_mode` for these tests so they don't
  require launching the binary.
- **Integration (manual, golden-path)**: launch `./build/dauntless`
  without the flag → confirm pause menu shows no dev section, F10 is
  a no-op, CEF JS console reports `window.__DAUNTLESS_DEV__` is
  `undefined`. Launch `./build/dauntless --developer` → confirm the
  dev section is visible, F10 still fires the shield-debug hit,
  `window.__DAUNTLESS_DEV__ === true`.
- **Smoke**: the existing `--smoke-check` mode is untouched; verify
  `./build/dauntless --smoke-check` still exits 0. Verify
  `./build/dauntless --smoke-check --developer` also exits 0 (the
  smoke path runs before dev-mode plumbing is observed, but the
  parsing must not regress).

## Alternatives considered

- **Compile-time `#ifdef DAUNTLESS_DEVELOPER`.** Provides the
  stronger "dev code never ships" guarantee but requires maintaining
  two build configurations and creates the risk that dev and release
  diverge. The project is pre-distribution; a runtime flag is
  sufficient and easier to test. Can layer compile-time stripping on
  later if a true release configuration becomes a concern.
- **Pure Python parsing of `sys.argv`.** Avoids the C++ getter but
  forces the renderer to call into Python to check dev state, which
  is a layering inversion and adds per-frame call cost for what
  should be a static bool.
- **Environment variable (`DAUNTLESS_DEVELOPER=1`).** Avoids argv
  plumbing but creates three independent read paths (C++, Python,
  JS-via-Python) that can disagree, and developers usually prefer a
  CLI flag to a shell prefix. The CLI form also leaves room for
  future sub-flags parsed in the same code path.

## Deferred work

- Per-keybinding category/grouping (input/render/AI) for a richer dev
  pause-menu listing — deferred until there are enough dev keys to
  warrant grouping.
- A developer console (REPL bound to a CEF panel) — deferred; will
  reuse the `.dev-only` infrastructure when built.
- Persistent dev default via `Options.cfg` — deferred until requested.
- Migrating remaining ad-hoc debug surfaces (e.g. radar-related
  toggles, physics inspectors) into the registry — opportunistic, not
  blocking on this change.
