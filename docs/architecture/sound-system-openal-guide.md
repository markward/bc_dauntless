# Faithful 3D Sound in OpenAL

A build-facing guide for reproducing Star Trek: Bridge Commander's 3D audio on **OpenAL Soft**.
The reference for *what BC actually does* is the RE doc
[`sound-system.md`](../../../STBC-Reverse-Engineering-1/docs/engine/sound-system.md) in the
STBC-Reverse-Engineering repo; this document is the *how to rebuild it*. All code here is original
illustration, not decompiled source.

> **Scope.** Reproduce BC's audible spatial behaviour on OpenAL Soft. **Reverb and the
> `TGSoundRegion` mute/muffle filters are deliberately out of scope** — they were barely used in the
> original (see the RE doc's OQ3). A no-op seam is kept in §11 so EFX can be added later.

**In scope:** the positional model, listener, emitters, attenuation, doppler, cones, 2D sounds,
category buses, the logical-name registry, `AttachToNode` tracking, the nearest-≤4-ship engine-hum
allocator, voice management, streaming, and the one-active-scene rule.
**Out of scope (by request):** reverb / EAX room types and the `TGSoundRegion` mute/muffle filters.
Stub the region hooks (§11) so they can be added later without touching the core.

## 0. Why this is mostly easy

OpenAL was designed as a cross-platform DirectSound3D work-alike, and BC's audio *is* DS3D
(under Miles). So the core is a near 1:1 port, and two things get **simpler** than the original:

- **No handedness flip.** BC negates Z on everything because NetImmerse is right-handed and DS3D is
  left-handed. **OpenAL is right-handed** — feed NI world transforms straight in. Do **not** port
  BC's Z-negation.
- **No hardware-voice scarcity.** BC's priority/group juggling existed for finite HW 3D voices.
  OpenAL Soft mixes in software (256 sources by default). Keep a pool + priority for mix clarity,
  but the forcing constraint is gone.

## 1. Architecture

Mirror BC's layering. The backend is the only part OpenAL replaces; everything above is your engine
plumbing and is identical regardless of backend.

```
  Game / mission scripts
        │  play "Galaxy Phaser", attach to node, set volume …
        ▼
  SoundManager  (logical-name registry, category buses, voice pool)   ← was TGSoundManager
        │  owns the one Listener; iterates Sounds each frame
        ▼
  Sound  (params + an OpenAL source handle)                           ← was TGSound
        │
        ▼
  OpenAL Soft  (alSource*, alListener*, AL_INVERSE_DISTANCE_CLAMPED)  ← was Miles/DS3D
```

Key invariants to preserve from BC:
- **Exactly one listener**, bound to the **active camera of the currently-rendered set**.
- **One active sound scene at a time.** Non-active sets stop their sources.
- Emitters follow a **scene-graph node's world transform** (`AttachToNode`), updated per frame.
- 3D vs 2D is a **per-sound flag** (BC's `LS_3D`; `flags==0` = 2D).

## 2. Backend setup (once)

```c
ALCdevice*  dev = alcOpenDevice(NULL);           // default output
ALCcontext* ctx = alcCreateContext(dev, NULL);
alcMakeContextCurrent(ctx);

alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED);    // ← THE faithful model. Not linear.
alDopplerFactor(1.0f);                            // DS3D default
alSpeedOfSound(SPEED_OF_SOUND_WORLD_UNITS);       // see §3 (units)
```

`AL_INVERSE_DISTANCE_CLAMPED` is the single most important choice — it is the same law DS3D uses.
Getting this wrong (e.g. `AL_LINEAR_DISTANCE`) is the one change that makes BC's audio sound wrong,
because linear **cuts off** at max distance whereas BC/DS3D **clamps** (a floor on loudness, never
silence). See §5.

## 3. The units decision (do this first — it is load-bearing)

**All settled from the binary on 2026-07-16 — no guesswork needed:**

- **BC overrides no DS3D global.** Rolloff factor, doppler factor and distance factor all stay at
  **1.0** (the three `AIL_set_3D_*_factor` symbols don't exist in the image at all). So
  `alDopplerFactor(1.0)` and `AL_ROLLOFF_FACTOR = 1.0` are exactly faithful.
- **`unitsPerMeter` defaults to 1.0** and is applied to **velocity only** — *not* to position, and
  *not* to min/max distances. Those stay in **raw game units**.

So: **keep OpenAL in the same unit space as the NI scene graph** and feed positions and velocities
straight in.

```c
alSpeedOfSound(343.3f);     // game units/sec — BC's unitsPerMeter=1.0 means 1 unit is treated as 1 m
alDopplerFactor(1.0f);
```

> **Do NOT port the ÷1000.** BC divides velocity by `unitsPerMeter × 1000` before handing it to
> Miles, because the **Miles API wants metres/millisecond**. That is a unit convention of the *API*,
> not a physical scaling. **OpenAL wants velocity in units/second**, the same space as
> `AL_SPEED_OF_SOUND`. Doppler depends only on the ratio `v/c`, which is identical either way —
> replicating the ÷1000 against a 343.3 speed of sound would make doppler ~1000× too weak.

> **A caveat worth knowing:** BC's `unitsPerMeter = 1.0` means *the engine treats one game unit as
> one metre for doppler*, regardless of the visual scale of the models. Reproducing that faithfully
> means adopting the same convention rather than "correcting" it. `alDopplerFactor` remains your
> tuning knob if you ever want to.

Write the chosen unit convention down once and never mix spaces.

## 4. The Listener — bind to the active camera each frame

The listener is the **active camera of the rendered set** (BC: the child of the set whose active flag
is set). Right-handed, no Z flip. `at` = camera forward world vector, `up` = camera up world vector.

```c
void UpdateListener(const Camera* cam, float dt) {
    Vec3 pos = cam->WorldPosition();
    Vec3 fwd = cam->WorldForward();     // NI world vectors, fed straight in
    Vec3 up  = cam->WorldUp();
    Vec3 vel = (pos - g_prevListenerPos) / dt;   // for doppler; or use physics velocity
    g_prevListenerPos = pos;

    float ori[6] = { fwd.x, fwd.y, fwd.z,  up.x, up.y, up.z };
    alListener3f(AL_POSITION, pos.x, pos.y, pos.z);
    alListener3f(AL_VELOCITY, vel.x, vel.y, vel.z);
    alListenerfv(AL_ORIENTATION, ori);
}
```

In space the active camera is the tactical/chase cam; on the bridge it's the bridge cam — same code,
because you always read *whichever* camera the rendered set says is active. That is exactly BC's
behaviour and it's why the exterior/interior split needs no special case here.

## 5. Attenuation — the faithful mapping (with BC's real numbers)

**The shipped constants, recovered from `TGSound::SetupFromFile` (`0x0070B360`):**

| Sound | reference (min) | max | gain | Notes |
|---|---|---|---|---|
| **Everything** — weapons, explosions, ambience, UI | **50.0** | **700.0** | 1.0 | the SetupFromFile defaults |
| **Ship engine hum** (the only exception) | **4.375** | **35.0** | 1.0 | the sole C++ tuning call site |

This is the whole story, and it is startlingly simple: **`TGSound_SetMinMaxDistance` has exactly three
xrefs in the entire binary** — the engine-hum allocator, the copy-constructor, and the SWIG wrapper
that no shipped script ever calls. **No weapon code touches it.** So one pair of numbers —
**50 / 700** — sets the loudness balance of essentially all of BC's combat audio.

Other shipped defaults worth copying: pitch **1.0**, volume **1.0**, priority **0.5**, and cone
**360°/360°/1.0** — i.e. **cones are disabled by default**, which is already OpenAL's default, so you
need no per-source cone work unless a sound explicitly sets one.

Per emitter:

```c
alSourcef(src, AL_REFERENCE_DISTANCE, 50.0f);   // BC default; 4.375f for the ship engine hum
alSourcef(src, AL_MAX_DISTANCE,       700.0f);  // BC default; 35.0f  for the ship engine hum
alSourcef(src, AL_ROLLOFF_FACTOR,     1.0f);    // BC never overrides this
```

> **Caveat on 4.375.** It is computed as `35.0 × 0.125` by a routine reachable only through a function
> pointer, so it could not be *statically proven* to run. If it doesn't, the engine-hum min is `0.0`.
> Either way the hum's **max of 35.0** is certain, and that is what makes it a tight, near-field
> sound versus the 700-unit reach of weapons.

The clamped inverse-distance gain OpenAL computes is:

```
d'   = clamp(distance, ref, max)
gain = ref / (ref + rolloff * (d' - ref))
```

At rolloff 1.0 this is **−6 dB per doubling of distance past `ref`** (d=2·ref → 0.5; d=4·ref → 0.25)
— identical to DS3D. Beyond `max`, `d'` is clamped, so gain **floors** at
`ref/(ref + rolloff*(max-ref))` and holds; it never reaches zero. **Reproducing this floor-not-cutoff
behaviour is what makes distant capital ships stay faintly audible, exactly like the original.**

Design note that transfers directly: **`ref` (minDistance) is the primary loudness control**, because
gain ≈ ref/d in the far field. Doubling `ref` roughly doubles far-field loudness. This is how BC keeps
a big ship audible across the map while a small emitter falls off fast — preserve the per-sound `ref`
values, not just the curve shape.

## 6. Doppler

Feed real velocities on both the listener (§4) and each moving source (§8). With
`alDopplerFactor(1.0)` and the speed of sound from §3, OpenAL's doppler matches DS3D's default. BC
feeds live ship velocities, so fast weapon/ship passes pitch-shift — keep that; don't zero source
velocities or you lose the effect.

## 7. The Sound object (was TGSound)

One struct = decoded parameters + an OpenAL buffer + (when playing) a source from the pool.

```c
typedef struct {
    ALuint  buffer;         // decoded WAV (mono for 3D; see note)
    ALuint  source;         // 0 when not playing; borrowed from the pool
    bool    is3D;           // BC LS_3D
    bool    looping;
    bool    streamed;       // §12
    float   volume;         // BC default 1.0  (TGSound+0x64), pre-bus
    float   pitch;          // BC default 1.0
    float   minDist;        // BC default 50.0   (4.375 for the ship engine hum)
    float   maxDist;        // BC default 700.0  (35.0  for the ship engine hum)
    float   coneInner, coneOuter, coneOuterGain;  // BC default 360/360/1.0 = DISABLED
    Category category;      // SFX / VOICE / INTERFACE (bus routing, §8)
    SceneNode* attachedNode;    // AttachToNode target, or NULL
    float   priority;       // BC default 0.5 (TGSound+0x68) — voice-stealing rank, NOT gain
    int     group;          // for bulk stop/unload
} Sound;
```

> **Mono-for-3D rule:** OpenAL only spatialises **mono** buffers. A stereo buffer plays 2D
> regardless of position. All BC 3D sfx are mono; keep them mono. 2D sounds (music, some UI) may be
> stereo.

Configure a source when the sound starts playing:

```c
void ApplySoundParams(Sound* s) {
    ALuint src = s->source;
    alSourcei(src, AL_BUFFER, s->buffer);
    alSourcef(src, AL_PITCH,   s->pitch);
    alSourcei(src, AL_LOOPING, s->looping ? AL_TRUE : AL_FALSE);
    alSourcef(src, AL_GAIN,    s->volume * BusGain(s->category));   // §10

    if (s->is3D) {
        alSourcei(src, AL_SOURCE_RELATIVE, AL_FALSE);
        alSourcef(src, AL_REFERENCE_DISTANCE, s->minDist);
        alSourcef(src, AL_MAX_DISTANCE,       s->maxDist);
        alSourcef(src, AL_ROLLOFF_FACTOR,     1.0f);
        if (s->coneOuter > 0.0f) {
            alSourcef(src, AL_CONE_INNER_ANGLE, s->coneInner);
            alSourcef(src, AL_CONE_OUTER_ANGLE, s->coneOuter);
            alSourcef(src, AL_CONE_OUTER_GAIN,  s->coneOuterGain);
        }
    } else {
        // 2D: listener-relative at origin, no attenuation. (Bridge, UI, music.)
        alSourcei(src, AL_SOURCE_RELATIVE, AL_TRUE);
        alSource3f(src, AL_POSITION, 0, 0, 0);
        alSourcef(src, AL_ROLLOFF_FACTOR, 0.0f);
    }
}
```

**`AttachToNode`** is the only positioning mechanism BC scripts use — they never set a position per
frame. Replicate: store the node; each frame copy its world transform into the source (§9). A one-shot
3D sound with no node stays where it was placed at play time.

## 8. The Manager (was TGSoundManager)

Responsibilities: the **logical-name registry**, the **category volume buses**, the **voice pool**,
and **groups** for bulk lifetime.

- **Registry:** `Load(file, name, flags)` decodes a WAV to an AL buffer and stores a `Sound` under a
  string `name`. Everything else is `GetSound(name)` / `PlaySound(name)`. Names are the API, not paths.
- **Buses:** master + SFX + voice + interface, each a 0..1 gain with an enable toggle. Final source
  gain = `sound.volume * bus[category] * master`. Recompute on bus change.
- **Voice pool:** pre-generate a pool of sources (e.g. 64–128). On `Play`, borrow a free source
  (reclaim any whose `AL_SOURCE_STATE == AL_STOPPED`); if none free, **evict the lowest-priority**
  playing 3D source. `MaxSoundsAtOnce` = pool size. OpenAL Soft's high source cap means you rarely
  evict.

> ### ⚠️ Priority is a rank, not a volume — BC's numbers go here, not on `AL_GAIN`
>
> BC's `TGSound+0x68` is **voice priority** (default **0.5**), proven by SWIG
> (`swig_TGSound_SetPriority` writes it, `GetPriority` reads it; volume is a *different* field,
> `+0x64`). The famous `0.9 local / remote` pair on the weapon fire path writes **this** field — it
> was mislabeled "sound gain" in the RE docs until 2026-07-16.
>
> Shipped values: **0.9** when the firing ship is the local player's; remote is **per-weapon** —
> **0.6** phaser, **0.5** pulse and tractor. Co-fired voices (phaser Start + Loop) get the second
> written at `priority − 0.01`.
>
> **Wire 0.9/0.6/0.5 into your eviction comparator, not `AL_GAIN`** — mapping them to gain would make
> every remote phaser 33% quieter than the original and leave priority flat.
>
> **Honest caveat:** BC's *consumer* of this field has **not been identified** (the function once
> claimed to read it turned out to be `DeleteSound`), so "lowest priority is evicted first" is the
> natural reading — consistent with `SetMaxSoundsAtOnce` existing — but is **not verified**, and the
> purpose of the `−0.01` is unknown. Since OpenAL Soft rarely forces eviction anyway, this is low-risk
> either way: implement the obvious comparator and move on.
- **Groups:** `StopAllInGroup(g)` / `DeleteAllInGroup(g)` for scene teardown (BC's `"BridgeGeneric"`,
  per-mission groups, etc.).

## 9. Per-frame update loop (order matters)

Reproduce BC's `SetClass::Update` + `UpdateSounds` + listener sequence, once per frame for the
rendered set. Batch the whole thing so OpenAL applies it atomically (the analog of DS3D's deferred
commit):

```c
void SoundFrame(const Set* renderedSet, float dt) {
    alcSuspendContext(g_ctx);            // begin atomic batch

    // (1) update attached emitters from their nodes
    for (Sound* s : g_playingSounds) {
        if (s->is3D && s->attachedNode) {
            Vec3 p = s->attachedNode->WorldPosition();
            Vec3 v = (p - s->prevPos) / dt;   s->prevPos = p;
            alSource3f(s->source, AL_POSITION, p.x, p.y, p.z);
            alSource3f(s->source, AL_VELOCITY, v.x, v.y, v.z);
            if (s->coneOuter > 0.0f) {
                Vec3 d = s->attachedNode->WorldForward();
                alSource3f(s->source, AL_DIRECTION, d.x, d.y, d.z);
            }
        }
    }

    // (2) nearest-<=4-ship engine hum allocator (§10-of-reference; BC UpdateSounds)
    UpdateShipHums(renderedSet);

    // (3) listener from the active camera
    UpdateListener(renderedSet->ActiveCamera(), dt);

    alcProcessContext(g_ctx);            // commit batch
}
```

## 10. The nearest-≤4-ship engine-hum allocator

This is BC's most distinctive positional behaviour and worth reproducing faithfully. Each frame, in
the active space set:

1. Take the listener (active camera) position.
2. Gather ships in the set that **have an impulse-engine subsystem** (BC gate: `ShipClass` with
   `ship+0x2CC != 0` — that field is the **ImpulseEngine subsystem**, and the hum is its sound).
3. Sort by distance to the listener; keep the **nearest 4**.
4. Reconcile against currently-humming ships: **stop** the hum on any ship that fell out of the top-4
   (return its source to the pool), **start** a looping 3D hum (attached to the ship's node) for any
   new ship that entered the top-4, at **reference 4.375 / max 35.0**.

The hum's sound **name** comes from the engine subsystem's property (a name string only — it carries
no distances and no gain; the caller supplies those). The original caps this at 4; the reason is not
established — keep it (or expose it as a tunable defaulting to 4) so the mix density matches BC.

## 11. The one-active-scene rule (and the region stub)

Only the rendered set is audible. On a set/view change, **stop every source belonging to the
now-inactive set** (BC flushes handles in `UpdateSounds`). Track each `Sound`'s owning set; when the
rendered set changes, stop sounds whose set != rendered set. This is what makes the bridge↔space
switch silence the other world, and it's why the viewscreen (space rendered *visually* on the bridge)
carries no audio — the space set isn't the active sound scene.

**Region stub (reverb/filters out of scope):** keep a no-op seam so it can be added later without a
rewrite:

```c
// Out of scope now; wire to OpenAL EFX (ALC_EXT_EFX) later if desired.
void Region_SetFilter(Set* set, FilterType f) { /* TODO: EFX aux slot + low-pass */ }
```

Because BC barely used room types, a flat (no-reverb) mix is faithful enough for the target.

## 12. Streaming (voice and music)

Long assets (crew dialogue, music) stream instead of fully decoding. Standard OpenAL double/triple
buffering:

```c
// setup: queue N (e.g. 3) filled buffers, then alSourcePlay(src)
// each frame:
ALint processed; alGetSourcei(src, AL_BUFFERS_PROCESSED, &processed);
while (processed--) {
    ALuint b; alSourceUnqueueBuffers(src, 1, &b);
    if (RefillFromDecoder(b))                 // decode next chunk into b
        alSourceQueueBuffers(src, 1, &b);
}
// guard against underrun: if the source stopped but data remains, alSourcePlay again
```

Music is a **separate 2D subsystem** in BC — keep it that way: stereo, `AL_SOURCE_RELATIVE`, its own
volume, never routed through the 3D positional path.

## 13. Weapon/engine sound conventions

- Weapon/engine sound *names* come from hardpoint data (`SetFireSound`, `SetEngineSound`). Resolve the
  name through the registry.
- **Phaser attack+sustain:** the base fire-sound name yields two registered sounds by suffix —
  `"<Name> Start"` (one-shot) and `"<Name> Loop"` (sustained). Play Start, then loop Loop until fire
  ends; on stop, fade/stop both. (The tractor plays the bare name; torpedo launch sounds come from the
  projectile module.)
- Randomised explosion/collision sets: pick from a name list with anti-repeat, exactly as BC's
  `GetRandomSound` does.

## 14. Footgun checklist

1. **Distance model must be `AL_INVERSE_DISTANCE_CLAMPED`.** Linear cuts off at max — wrong feel.
2. **Keep one unit space** (scene units). Set `AL_SPEED_OF_SOUND` and per-sound ref/max in those units.
3. **Do NOT port BC's Z-negation.** NI and OpenAL are both right-handed; feed transforms directly.
4. **Do NOT port BC's velocity ÷1000.** That is a Miles API convention (m/ms); OpenAL wants units/sec.
5. **3D sources must be mono.** Stereo buffers ignore position.
6. **`ref` (minDistance) is the loudness knob** — and BC's value is **50.0** for everything except the
   engine hum (**4.375**). No guessing required; see §5.
7. **`0.9 / 0.6 / 0.5` are PRIORITY, not gain.** Wire them to voice stealing (§8), never `AL_GAIN`.
8. **360 is an angle, not a distance.** BC's cone defaults are 360°/360° (disabled) at +0x40/+0x44;
   minDistance is 50.0 at +0x5c. A wrong Ghidra comment conflated these — don't re-derive it.
9. **maxDistance clamps, not cuts.** That floor is audible and correct.
10. **2D = `AL_SOURCE_RELATIVE` at origin, rolloff 0.** Use for bridge/UI/music.
11. **Reclaim stopped sources** back to the pool; don't leak the finite (if large) source set.
12. **Batch per frame** with `alcSuspendContext`/`alcProcessContext` to avoid partial-frame artifacts.
13. **Headless server runs none of this** — audio is pure client presentation of replicated events.

## 15. Milestone plan

1. **Backend + listener + one 3D source.** Prove attenuation and that a sound pans/attenuates as the
   camera moves. (Nails §2–§5.)
2. **Registry + manager + category buses + 2D sounds.** Bridge ambience/UI/music play; volumes work.
3. **`AttachToNode` + per-frame update + doppler.** A moving ship's engine tracks and pitch-shifts.
4. **Voice pool + groups + one-active-scene switching.** Bridge↔space silences the other world.
5. **Ship-hum allocator (nearest-≤4).** Match BC's ambient density.
6. **Streaming voice + music.** Dialogue and score.
7. *(Later, optional)* EFX reverb + region filters via the §11 seam.

## See also

In the **STBC-Reverse-Engineering** repo (the RE side — what the original actually does):

- [`docs/engine/sound-system.md`](../../../STBC-Reverse-Engineering-1/docs/engine/sound-system.md) — the RE reference: Miles/DS3D backend, TGSound layout, listener, addresses/offsets
- [`docs/engine/renderer-function-map.md`](../../../STBC-Reverse-Engineering-1/docs/engine/renderer-function-map.md) — `SetClass`/`SetManager`, the main loop, camera
