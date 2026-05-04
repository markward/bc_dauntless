# Open Questions for Python Injection Investigation

These questions cannot be answered from static analysis of the source alone.
Each requires a targeted instrumentation session against the running game.
All are answerable via the `Appc` wrapper logging approach before significant
reimplementation work begins.

**Status key:** ❌ Open — ✅ Answered by static analysis — ⚠️ Partial

---

## Q1 — Tick Rate ❌

**Question:** What is the game loop tick rate? Is it fixed or variable?

**Why it matters:** All `TimeSliceProcess` delays are specified in seconds.
Their actual granularity depends on how often the loop ticks. Physics
integration accuracy and AI polling intervals are both affected.

**Instrumentation approach:** Log `GetUpdateNumber` with a wall-clock
timestamp on each change. Average deltas over 30 seconds of gameplay.
Check variance to determine fixed vs variable.

**Expected answer:** Likely 20Hz or 30Hz fixed simulation tick, based on
timer granularity visible in source and era of engine.

---

## Q2 — Subsystem Update Ordering Within a Tick ❌

**Question:** Within a single tick, what order do subsystems update?
Specifically — does physics integrate before or after AI runs? Do events
fire before or after physics? Does Python get called before or after
the renderer?

**Why it matters:** An AI reading a ship position before physics has
integrated for that frame will make different decisions than one reading
after. Ordering affects correctness of combat AI and mission trigger timing.

**Instrumentation approach:** Log `GetUpdateNumber` alongside every
significant `Appc` call category — physics reads, AI callbacks, event
dispatch, render calls. Sort by frame number and wall-clock time to
reconstruct the within-tick call sequence.

**Specific calls to watch:**
- `PhysicsObjectClass` position/velocity reads and writes
- `ArtificialIntelligence` update callbacks
- `TGEventManager` dispatch calls
- `TGTimerManager` tick calls

---

## Q3 — Time Scale Interaction with Physics and AI ⚠️

**Question:** When `SetTimeScale()` is called (e.g. for slow motion cinematic
mode), does the physics integrator receive a scaled delta-time, or is
something else happening? Does AI decision-making slow proportionally?
Do `g_kTimerManager` timers slow while `g_kRealtimeTimerManager` timers
continue at wall-clock speed?

**Why it matters:** Determines whether slow mode is purely cosmetic
(renderer slows, logic continues at full rate) or whether it genuinely
scales the entire simulation. Affects how `SetTimeScale` must be
implemented in the replacement engine.

**Static analysis update:** `MissionLib.py:93–121` confirms the two-timer
architecture. Mission-critical timers and episode timers are tracked and
cleaned up separately (`DeleteAllMissionTimers`, `DeleteAllEpisodeTimers`),
implying the game actively expects the two clocks to diverge. This is
consistent with `g_kRealtimeTimerManager` continuing at wall speed during
slow motion. Whether `g_kTimerManager` slows proportionally to
`SetTimeScale` still requires instrumentation to confirm.

**Instrumentation approach:** Call `SetTimeScale(0.5)` during a session.
Log `GetGameTime` and `GetRealTime` readings at each frame alongside
`GetUpdateNumber`. Measure AI callback frequency and timer fire times
relative to both clocks.

**Specific scenario:** Trigger a cinematic sequence that uses slow mode,
log throughout, compare game time progression to real time progression.

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
| Q1 Tick rate | High — affects all timing | Very low — 5 minutes | ❌ Open |
| Q2 Update ordering | Medium-high — affects AI/physics interaction | Medium — one focused session | ❌ Open |
| Q3 Time scale | Medium — affects cinematic mode only | Low — trigger one cinematic | ⚠️ Partial |
| Q4 Process priorities | Low — C++ internal only | — | ✅ Answered |

**Recommended order:** Q1 first (quick win, unblocks everything else),
Q3 second (quick, self-contained), Q2 third (requires more careful
instrumentation setup). Q4 is closed — no instrumentation needed.

---

## Notes

- Q4 is closed by static analysis. The remaining three questions (Q1, Q2,
  Q3) are answerable in a single instrumentation session once the `Appc`
  wrapper logging infrastructure is in place.
- Q1 should be answered before any physics or timer implementation work begins.
- Q2 should be answered before AI integration work begins.
- Q3 is partially answered — the two-timer architecture is confirmed.
  Only the scaling behaviour under `SetTimeScale` still needs measurement.
- The BC modding community documentation may already answer Q1 — check
  BCFiles and related modding wikis before instrumentation.
