# Dauntless crew dialogue

Crew lines that have no BC original — written and voiced for Dauntless —
and the first feature that speaks them.

## Authoring a line

1. Add an entry to `tools/dialogue/dauntless_crew.json`: `key`, `text`
   (the subtitle), `sound` (game-root-relative voice file).
2. Put the voice file at `native/assets/replacements/<sound>`.
3. Run `uv run python tools/gen_dauntless_tgl.py --write`.

Keys follow BC's `<Speaker><Line><N>` style (`BrexRadiationShields1`), and
the voice file is named after its key, as BC's are
(`sfx/Bridge/Crew/Engineering/BrexRadiationShields1.wav`).

Never hand-edit `native/assets/replacements/data/TGL/Dauntless Crew.tgl`.
`tests/tools/test_dauntless_dialogue_drift.py` fails when it differs from
the JSON, when a voice file is missing, or when a WAV is in a format the
native decoder rejects (`native/src/audio/src/wav.cc`: PCM only — not
WAVE_FORMAT_EXTENSIBLE — 1-2 channels, 8 or 16 bit; any sample rate).

## Why it just works

- **Layout.** `engine.missions.tgl_reader.write_tgl` writes BC's own
  header (magic `0x1701`) and TOC. It reproduces all 57 stock TGLs byte for
  byte (`tests/missions/test_tgl_reader_roundtrip.py`), so the file is one
  `stbc.exe` would read too.
- **Lookup.** Both the TGL and the voice files live under the project's
  replacements overlay (`engine/mods.py:replacements`), which
  `paths.game_asset` consults first. So
  `App.g_kLocalizationManager.Load("data/TGL/Dauntless Crew.tgl")` and the
  officer's `SpeakLine(db, key, priority)` behave exactly as for an SDK line:
  subtitle, voice, lip-sync, priority arbitration.
- **Lip-sync.** No `.LIP` file ⇒ random mouth flap, which is BC's own
  fallback for its many lines without one (`engine/lip_sync_runtime.py`).
- **Search order.** The replacements `data/TGL` folder now leads
  `paths.game_asset_dirs("data/TGL")` and `name_resolver._tgl_roots()`.
  Tests that assert those lists must point `mods.replacements_root` at an
  empty tree.

## Language

There is no language selection. Subtitles are whatever the TGL holds, and
the stock install read here is English only. Per Mark, BC's localized
releases translated subtitle text but kept English voices, so a translation
would need only another TGL's text, not new recordings — unverified.

## "Raise shields" prompts — `engine/appc/crew_hazard_prompts.py`

| Hazard | Level at the player | Threshold | Lines |
|---|---|---|---|
| Asteroids | max(radial profile `asteroids`, rock-field strength `far_tier.field_strength_at`) | > 0.05 | `BrexAsteroidShields1` (Engineer), `MiguelAsteroidShields2` (Science) |
| Radiation | radial profile `radiation` | > 0.1 | `BrexRadiationShields1`, `BrexRadiationShields2` (Engineer) |

- Speaks only with the shields down (`nebula_runtime._shields_up`).
- Polled at 1 Hz on game time from `host_loop` beside the contact manager
  (sim-gated); reset on mission swap in `_reset_sensor_state`.
- One prompt per exposure. It re-arms when the level drops below half the
  threshold or the shields go up, never sooner than 120 s after the last
  prompt for that hazard. So hovering at a field's edge does not nag, and
  lowering shields inside a field gets at most one reminder per 2 minutes.
- Line chosen at random; if that officer is not on the bridge, the other
  line is used; if none is, the prompt stays pending.
- `CSP_SPONTANEOUS` (BC's engineer-report priority).
- **Never over dialogue** (Mark, 2026-10-07). If a scripted sequence still
  has a line to come (`actions.scripted_line_pending`, nested sequences
  included) or any crew line ended under 5 s ago (`crew_speech.silent_for`),
  the prompt is **dropped** for this exposure, not deferred. Why: missions
  play dialogue as sequences with gaps between lines (3,909 sequenced speak
  actions vs 54 direct `SayLine` calls in Maelstrom), and a prompt started in
  a gap was cut off by the next scripted line. Headless, E1M2 reads as
  dialogue for its ~50 s opening and then clears; Quick Battle never does.
  Launched sequences are forgotten on mission swap
  (`actions.reset_launched_sequences`), so a sequence an old mission left
  playing cannot block prompts forever.
- Skipped: E3M2 and E3M4 (their scripts prompt for shields themselves:
  `E3M2ProdRaiseShields`, `E3M4ShouldRaiseShields`), cinematics, warp, dash.

Live-verified (Mark, 2026-10-06): the asteroid prompt. ⚠️ The radiation prompt has not been seen in game yet.

## Dialogue patches — insert and replace lines in BC's missions

Spec: `docs/superpowers/specs/2026-10-07-dialogue-patches-design.md`.
Data: `native/assets/dialogue/patches.json` (read by the game at runtime,
so it lives with the assets, not in `tools/`). Always applied.

- **Insert:** `insert_after` under a TGL path lists lines to play after an
  anchor line. The anchor `CharacterAction` plays them before it completes
  (`CharacterAction.Completed` → `dialogue_patches.insert_actions`), so the
  mission's following steps wait. Sequenced lines only, not direct
  `SayLine` calls. Missing speaker or line: skipped, dev-logged.
- **Replace:** `replace` entries override a key's text and/or sound when
  the TGL loads (`TGLocalizationManager._build_database`), and can add a
  key BC never had. A replacement voice mirrors BC's folder as `.wav` under
  `native/assets/replacements/` so it never shadows BC's `.mp3`. ⚠️ Patches
  are re-read from disk on every use, but that only reaches inserts, which
  are looked up live each time an anchor completes; a `replace` edit reaches
  only TGL databases **built after** the edit, because
  `TGLocalizationManager` caches a built database per filename — a database
  already loaded keeps its old text/sound until it is evicted and rebuilt
  (e.g. a fresh mission load), not on the next read of `patches.json`.
- **Where files go:** a cut BC line needs only a `patches.json` entry; a
  newly recorded line goes through `dauntless_crew.json` (text) +
  `replacements/sfx/...` (voice) + an insert with `"tgl": "data/TGL/Dauntless Crew.tgl"`.
- First use: E1M2's replicator exchange (`2a`, `3a` Soams; `3b` Saffi;
  `4a` Brex), present in `E1M2.TGL` with voices but never scripted by BC —
  heard in game (Mark, 2026-10-07). First `replace`: Felix's
  `E1M2FirstHail6` with Mark's red-alert recording, voice and subtitle
  live-verified.
- Guards: `tests/tools/test_dialogue_patches_content.py` (every entry points
  at real content), `tests/integration/test_e1m2_supply_transfer.py`.
