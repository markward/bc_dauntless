# dauntless

Open reimplementation of the Bridge Commander engine.

## Legal notice

This project is an independent engine reimplementation. It does not include any game assets, scripts, or content from Star Trek: Bridge Commander. A legitimate retail copy of Star Trek: Bridge Commander is required to use this software.

This project is not made by, affiliated with, or supported by Activision or Paramount.

## Setup

Drop your BC installation into `game/` and your BC SDK into `sdk/`.

```bash
uv sync
uv run pytest
```

See `docs/project/gap_analysis.md` for the engine gap analysis and implementation phases.

## Running the renderer

Build the renderer host from the project root, then launch the binary directly:

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless
```

Keys: WASDQE flies the ship · 1-9/0/R throttle · arrow keys orbit the camera · scroll wheel zooms · C resets · F8 toggles the RmlUi debugger overlay · F9 toggles UI visibility.

## NIF parser corpus test

`native/tools/scan_nifs/` is a C++ binary that walks a directory tree, runs `nif::load` on every `.nif` file, and reports per-file outcomes — files that reached `End Of File`, files where the walker stopped on an unknown block type (grouped by type), and files that threw (grouped by message). It exits 0 only if every file reached EOF.

It's wired up as a ctest target (`scan_nifs_corpus`) that points at `game/data` when a BC install is present. The test is registered conditionally — if `game/data` is absent, no test is added (CI without assets just skips it). Re-run cmake configure after dropping in `game/`.

```bash
cmake -S native -B build
cmake --build build --target scan_nifs
ctest --test-dir build -R scan_nifs --output-on-failure
```

You can also run the binary directly against any directory tree:

```bash
./build/tools/scan_nifs/scan_nifs game/data
```

## Game-loop harness

`tools/gameloop_harness.py` discovers every SDK mission script, calls `Initialize(pMission)`, fires `ET_MISSION_START`, and advances the headless `GameLoop` for N ticks per mission. It reports per-mission pass/init-fail/loop-fail status and a grouped error summary — useful for catching regressions across the full mission corpus.

```bash
uv run python tools/gameloop_harness.py              # default: 36000 ticks (~10 min @ 60 Hz)
uv run python tools/gameloop_harness.py --ticks 600  # shorter run
uv run python tools/gameloop_harness.py --profile    # adds a ranked stub-call profile
```

## TGL harness

`tools/tgl_harness.py` walks every `.tgl` file under `game/data/TGL/` and `sdk/Build/Data/TGL/`, parses each via `engine.missions.tgl_reader.read_tgl`, and reports per-file pass/fail plus a grouped error summary. A file passes if it decodes to at least one string or sound; it fails on a parse exception or if it parses to an empty TGL. Missing roots are skipped silently so checkouts without a `game/` install still work.

```bash
uv run python tools/tgl_harness.py
```

## References & acknowledgements

The Phase 2 NIF parser draws on two open-source projects:

- **[OpenMW](https://openmw.org/)** — its NIF parser
  (`components/nif/`) is mirrored into `native/third_party/openmw_nif/` and
  used as a test-only diff oracle. Many thanks to the OpenMW team for
  building and maintaining a robust, GPL-licensed NIF implementation we can
  hold our own work to.
- **[NifSkope](https://github.com/niftools/nifskope)** — its `nif.xml`
  schema is the authoritative documentation for NIF block layouts and
  explicitly includes Bridge Commander in its compatibility list. Thanks
  to the NifTools / NifSkope team for keeping the format documented.

See `THIRD_PARTY_NOTICES.md` for the formal attribution.
