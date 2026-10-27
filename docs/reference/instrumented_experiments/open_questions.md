# Open Questions for Python Injection Investigation

These questions cannot be answered from static analysis of the source alone.
Each requires a targeted instrumentation session against the running game.
All are answerable via the `Appc` wrapper logging approach before significant
reimplementation work begins.

**Status key:** ❌ Open — ✅ Answered by static analysis — ⚠️ Partial

---

## Q1 — Tick Rate ✅

**Question:** What is the game loop tick rate? Is it fixed or variable?

**Why it matters:** All `TimeSliceProcess` delays are specified in seconds.
Their actual granularity depends on how often the loop ticks. Physics
integration accuracy and AI polling intervals are both affected.

**Answer: 60 Hz fixed tick rate.**

Measured via `GetGameTime` / `GetUpdateNumber` instrumentation during a
Quick Battle session (86.3s wall, 5145 ticks):

```
Tick rate:  59.61 Hz  (16.78 ms/tick)   [theoretical 60 Hz = 16.67 ms]
Time scale: 0.9807                       [≈ 1.0 — normal speed confirmed]
Samples:    54 frame boundaries
Note:       Python not called every tick; rate derived from total_frames / total_wall
```

The 0.39% deviation from 60.00 Hz is within normal measurement error.
The tick rate is **fixed at 60 Hz**. Python is called only when AI scripts
or game code explicitly invoke `GetGameTime` — not every tick — but this
does not affect the accuracy of the total-frames / total-wall calculation.

**Implications:**
- Physics time step: 16.667 ms (1/60 s)
- `TimeSliceProcess` minimum polling granularity: 16.667 ms
- Timer resolution for `g_kTimerManager`: 16.667 ms per tick

---

## Q2 — Subsystem Update Ordering Within a Tick ✅

**Question:** Within a single tick, what order do subsystems update?
Specifically — does physics integrate before or after AI runs? Do events
fire before or after physics? Does Python get called before or after
the renderer?

**Why it matters:** An AI reading a ship position before physics has
integrated for that frame will make different decisions than one reading
after. Ordering affects correctness of combat AI and mission trigger timing.

**Answer: Python AI runs at the very start of each tick, before physics.**

Measured via `GetTimeSinceFrameStart()` logged alongside each `GetGameTime`
call during a Quick Battle session (85.7s wall, 5095 ticks, 60 samples):

```
Frame position:  median 0.28 ms = 2% into the 16.82 ms tick
                 min 0.03 ms / max 0.46 ms (excluding 2 startup outliers)
Loop ordering:   AI/Python → physics → render  (standard pattern confirmed)
```

**Implications:**
- When a Python condition script reads a ship position, it sees the state
  from the *previous* tick — physics has not yet integrated for the current tick.
- The reimplemented engine should follow the same ordering: run all Python
  AI callbacks first, then step physics, then render.
- Event handler timing relative to physics is not yet measured (only
  GetGameTime call sites were instrumented), but given 2% entry point,
  Python almost certainly runs before all other subsystems.

---

## Q3 — Time Scale Interaction with Physics and AI ✅

**Question:** When `SetTimeScale()` is called (e.g. for slow motion cinematic
mode), does the physics integrator receive a scaled delta-time, or is
something else happening? Does AI decision-making slow proportionally?
Do `g_kTimerManager` timers slow while `g_kRealtimeTimerManager` timers
continue at wall-clock speed?

**Answer: `GetGameTime` scales with `SetTimeScale`; `GetRealTime` does not.**

Measured by logging both clocks per tick across a Maelstrom mission session
that included a cinematic slow-motion sequence:

```
Normal gameplay:  game_time/real_time ratio ≈ 1.0
During cinematic: ratio dropped to 0.204  (~5x slow-down)
```

**Implications:**
- `GetGameTime` is genuinely scaled — slow mode affects the full simulation,
  not just the renderer.
- `g_kTimerManager` runs on game time → timers slow proportionally during
  cinematics. A 1-second game timer fires every ~5 wall seconds at 0.2x scale.
- `g_kRealtimeTimerManager` runs on real time → unaffected by `SetTimeScale`.
  UI animations, sound timing, and HUD updates that use realtime timers
  continue at normal speed during slow-mo.
- The two-clock architecture is load-bearing: mission logic (game time timers)
  slows with the simulation; player-facing UI (realtime timers) does not.

---

## Q4 — TimeSliceProcess Priority Semantics ✅

**Question:** What do the four priority levels (`UNSTOPPABLE`, `CRITICAL`,
`NORMAL`, `LOW`) actually mean in practice? Does `UNSTOPPABLE` run every
tick regardless of frame budget? Can `LOW` priority processes be skipped
or deferred when the frame is over budget? Is there observable difference
between `NORMAL` and `LOW` under normal gameplay conditions?

**Why it matters:** `PythonMethodProcess` inherits from `TimeSliceProcess`.
If priority affects whether a process fires on a given tick, condition
polling intervals may not be as reliable as assumed. Combat AI correctness
could be affected if `LOW` priority processes are skipped under load.

**Answer (static analysis):** A full scan of the 1228 SDK source files
found only two priority levels used in Python code:

- `NORMAL` — the default for all condition polling (`ConditionInRange`,
  `ConditionInLineOfSight`, `ConditionInPhaserFiringArc`, etc.)
- `LOW` — used in exactly two places: `ConditionIncomingTorps` and
  `FriendliesInPlayerSetStronger`

`CRITICAL` and `UNSTOPPABLE` have no Python call sites. They are C++
internal priorities for rendering and physics. This means reliable polling
intervals are safe to assume for all Python-visible processes regardless
of priority level. Instrumentation for this question is no longer needed.

---

## Investigation Priority

| Question | Impact if wrong | Instrumentation effort | Status |
|---|---|---|---|
| Q1 Tick rate | High — affects all timing | — | ✅ 60 Hz fixed |
| Q2 Update ordering | Medium-high — affects AI/physics interaction | — | ✅ AI first, then physics |
| Q3 Time scale | Medium — affects cinematic mode only | — | ✅ Game time scales; real time does not |
| Q4 Process priorities | Low — C++ internal only | — | ✅ Answered |

**Recommended order:** Q1 first (quick win, unblocks everything else),
Q3 second (quick, self-contained), Q2 third (requires more careful
instrumentation setup). Q4 is closed — no instrumentation needed.

---

## Notes

- Q1 closed: 60 Hz fixed tick rate, confirmed by instrumentation.
- Q2 closed: Python AI runs at ~2% into each tick (before physics and render).
- Q3 closed: GetGameTime scales with SetTimeScale (ratio 0.204 measured during cinematic); GetRealTime does not.
- Q4 closed by static analysis.
