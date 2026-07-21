# CharacterClass — reference specification (tier-0)

> **Provenance / evidence tier.** This is the clean-room behavioural specification Mark supplied,
> derived from the reverse-engineering effort and **recompiled into a hybrid executable and
> gameplay-tested**. Per the `project-evidence-tiers-sdk-swig-re` memory it is **tier 0** — trust its
> findings over any other source (including the sibling `../STBC-Reverse-Engineering-1/` static
> decompilation) where they overlap. Contains no original code; virtual addresses (VA) are
> cross-reference anchors only. It is the driving reference for the CharacterClass reimplementation
> (SP1 merged; SP2 the AnimationQueue in progress — see
> `docs/superpowers/specs/2026-07-21-characterclass-reimplementation-sp*-design.md`).

## 1. Overview

`CharacterClass` models an **interactive bridge/away-team character**: a rigged actor with a body +
head NIF (Gamebryo scene model), an animation queue, a speaking/sound queue, a phoneme table
(lip-sync), a status/tooltip UI, a per-character "location" concept, and a right-click context menu.
It is driven heavily from Python: many actions resolve an animation or location by calling a Python
bridge function and playing the returned object through the animation queue.

- **Base chain:** `BaseObjectClass → ObjectClass → … → CharacterClass`. Immediate reconstructed base
  is the `ObjectClass` root constructor (`0x00435030`), supplying a virtual destructor.
- **`sizeof`:** `0x1B4` bytes. **Own vtable:** `0x008948AC`. **Class ID (RTTI/IsKindOf):** `0x8016`.

## 2. Object model (offsets from object base; ptr/int/uint/float = 4 bytes, byte = 1)

| Offset | Type | Name | Meaning |
|--------|------|------|---------|
| `+0x00` | ptr | vtable | Own vtable `0x008948AC`. |
| `+0x18` | ptr | m_pObj18 | Sub-object; `SetFlags`/`ClearFlags` dispatch its slot `+0x50` for the 0x10/0x100 flag values; `MenuUp` consults its veto predicate slot `+0x54`. Its `+0x54` cluster (3 ints) zeroed on location change. |
| `+0x68` | char* | m_pHeadName | strdup of the head-NIF / third init argument. |
| `+0x6c` | char* | m_pBodyName | strdup of the body/base name (first init argument). |
| `+0x74` | char* | m_pYesSir | "Yes-Sir" acknowledgement line (owned). |
| `+0x7c` | uint | — | Initialised to `1`. |
| `+0x80` | uint | m_flags | **State-flag bitfield** (§3). |
| `+0x84` | uint | — | Initialised to `2`. |
| `+0x88` | char* | m_pName | Character name (owned). |
| `+0x8c` | ptr | m_pSpeakQueue | Speaking/sound-queue sub-object (0x60 bytes; created only when ctor `param2 == 0`). |
| `+0x90` | ptr | m_pAnim | Animation-factory sub-object (0x18 bytes). `Make(name)` builds an animation by name. |
| `+0x98` | float | — | `0.5` (default). |
| `+0x9c` | char* | m_pLocName | Location-name prefix used to compose animation names (`"%s…"`). |
| `+0xa0` | char* | m_pTargetName | Owned name buffer for the active "move/back-to" target (state bit 0x4). |
| `+0xa4` | char* | m_pGlanceName | Owned name buffer for the active "glance-away" target (state bit 0x2). |
| `+0xa8` | int | m_nPositions | Count of position-zoom records. |
| `+0xac` | ptr | m_pPositions | Array of position-zoom records, 0x18 bytes each. |
| `+0xb8` | float | — | `0.1` (default). |
| `+0xbc` | char* | m_pBlink | Blink-animation name (owned). |
| `+0xc0` | uint | m_uC0 | Glance/turn sentinel; set to `0xC0000000` by GlanceAway/TurnBack. |
| `+0xc8` | float | — | `-(timer.query(0x1E))` — negative time constant captured at construction. |
| `+0xcc` | byte | m_bActive | Character is active/awake. |
| `+0xd0` | float | — | `-1.0` (default). |
| `+0xd4` | ptr | m_pStatusUI | Status/tooltip UI container (lazily created via Python bridge in `SetStatus`). |
| `+0xd8` | — | m_statusHash | Embedded status hash-map. key `0..5` → widget/value. |
| `+0xe8`/`+0x104`/`+0x120` | — | m_list2/3/4 | Three embedded pointer-array/list blocks (bulk-freed by `ClearAnimations`). |
| `+0x148` | ptr | m_pDatabase | Registered database handle (`SetDatabase`). |
| `+0x14c` | ptr | m_pMenuState | Menu-state object. Menu id at `+0x14c`; ready-flag byte at its `+0x28` (bit 0x1). |
| `+0x150` | int×3 | m_vecDefault | Three ints copied from fixed default-vector constants at construction. |
| `+0x15c` | ptr | m_pCurAnim | Current animation **record**. |
| `+0x160` | uint | m_uiCount | Number of queued animation records. |
| `+0x164` | ptr | m_pAnimList | Animation queue **head** node. |
| `+0x168` | ptr | m_pAnimListTail | Animation queue **tail** node. |
| `+0x16c` | ptr | m_pAnimFreeList | Recycled queue-node freelist. |
| `+0x170` | ptr | m_pBlocks | Slab-allocation block list backing the freelist. |
| `+0x174` | int | m_nPerBlock | Queue nodes per slab block (`2`). |
| `+0x178` | uint | — | `0xFFFFFFFF` (default). |
| `+0x180` | ptr | m_phonemeGuard | Phoneme feature guard: if 0, `AddPhoneme` is a no-op. |
| `+0x184` | — | m_phonemeHash | Embedded phoneme hash-map. key(int) → dup'd name. |
| `+0x198` | — | m_hash5 | Fifth embedded hash-map (vtable `0x8949B8`, capacity 0x25). |
| `+0x1b0` | byte | m_bMenuEnabled | Context-menu enabled. |

**Position-zoom record (0x18 bytes):** `+0x00` name (owned) · `+0x04` zoom value (float) · `+0x08`
look-at/zoom-target name (owned, may be null).

**Anim record (`AnimRec`, 0x10 bytes):** `+0x00` scene/animation object pointer · `+0x04` state-flag
bits to apply while playing · `+0x08` category code (§3) · `+0x0C` owned name buffer (may be null).
**Queue node (0xC):** `+0x00` record ptr · `+0x04` next · `+0x08` prev.

## 3. Constants

**State-flag bits (`m_flags` @ +0x80)** — set/cleared via SetFlags/ClearFlags, tested via IsStateSet:

| Bit | Meaning |
|-----|---------|
| `0x01` | Standing (SetStanding). |
| `0x02` | Glance-away active (owns `+0xa4`; cleared when the glance-away anim releases). |
| `0x04` | Move/back-to-target active (owns `+0xa0`; cleared when that anim releases). |
| `0x08` | Busy / menu-suppressed — set by MoveTo; MenuUp refuses while set; drives tooltip suppression. |
| `0x20` | Initiative (SetInitiative). |

Two flag *values* are dispatched to `m_pObj18` (not stored in `m_flags`): `0x10` → slot `+0x50`(1) on
SetFlags, (0) on ClearFlags (visibility/enable toggle); `0x100` → the inverse.

> Public `CS_*` → value mapping (from the extracted `stbc_constants.csv`, tier 1, where this doc gives
> only bit meanings): `CS_STANDING=0x1, CS_GLANCING=0x2, CS_TURNED=0x4, CS_UI_DISABLED=0x8,
> CS_HIDDEN=0x10, CS_INITIATIVE=0x20, CS_MIDDLE=0x40, CS_SEATED=0x80, CS_VISIBLE=0x100,
> CS_CLEAR_GLANCE=0x200, CS_CLEAR_TURNED=0x400, CS_UI_ENABLED=0x800, CS_STOP_INITIATIVE=0xFD8`.

**Animation category codes (`AnimRec+0x08`, and the mode arg to SetCurrentAnimation):**

| Code | Meaning | Interruptable? |
|------|---------|----------------|
| `0` | Idle / breathe / speak-support. | yes |
| `1` | General play (mode > 0 playback). | yes |
| `2` | Locomotion / non-interruptable action (move-to, mode ≤ 0 playback). | **no** |
| `4` | Turn-back. | special |
| `5` | Glance-at. | yes |
| `6` | Glance-away. | yes / special |

Predicates: interruptable iff code ∈ {0,1,5,6}; non-interruptable iff code == 2.
`ClearAnimationsOfType(code)` removes all queued records of a category; the "clear the interruptable
set" call is codes `0,1,5,6`.

> Full `CAT_*`: `BREATHE=0, INTERRUPTABLE=1, NON_INTERRUPTABLE=2, TURN=3, TURN_BACK=4, GLANCE=5,
> GLANCE_BACK=6`. Status keys `0..5` (SetStatus/ClearStatus; out-of-range ignored).

**Key collaborators:** NIF loader `0x009976B0` (LoadBody/LoadHead); character-set registry
`0x0097E9C8`/`0x0097E9CC`; `TG_CallPythonFunction` `0x006F8AB0`; `Fn006F8F70` (unwrap Python→engine
ptr); `Fn006F0EE0` (record's scene ptr → live animation object, or null); `m_pAnim->Make(name)`
`0x0045F810`.

**Python-bridge idiom:** call + DECREF(arg) + DECREF(result) + error-clear on `-1` return.

## 4. Methods (confidence: BE=byte-exact, DE=differential-verified, LV=logic-verified, P=partial)

### 4.1 Lifecycle

- **Create (static)** `Create(a0, bodyNIF, headNIF)` VA `0x00667D10` (BE). Alloc 0x1B4, run ctor,
  call `InitFromNIFs(a0, bodyNIF, headNIF)`, return.
- **Constructor** `CharacterClass(param2)` VA `0x00666F10` (LV). Base ctor + own vtable; build the
  embedded maps/lists; zero queue fields (`m_nPerBlock=2`); alloc anim-factory `+0x90`; defaults
  `+0x7c=1, +0x84=2, +0x98=0.5, +0xb8=0.1, +0xd0=-1.0, +0xc8=-(timer 0x1E), +0x178=0xFFFFFFFF,
  m_bMenuEnabled=1`; **only if param2==0** alloc speak-queue `+0x8c`; `SetInitiative(1)`.
  > Field-named ctor defaults (from sibling agent-memory, tier 1): Size `+0x78`=0(SMALL),
  > Gender `+0x7C`=1(FEMALE), AudioMode `+0x84`=2(CAM_VOCAL), BlinkChance `+0xB8`=0.1,
  > RandomAnimationEnabled `+0x13C`=1, BlinkStages `+0x178`=-1, IsActive `+0xCC`=0.

### 4.2 Identity & basic setters (free-old / dup-new / null-clear pattern)

- `SetCharacterName`/`SetName`/`SetYesSir`/`SetLocationName`/`SetBlinkAnimation`/`SetDatabase` — as named.
- **SetActive** `SetActive(bActive)` VA `0x0066AE10` (BE). Store into `m_bActive`. **If deactivating
  (0), clear the interruptable animation set via `ClearAnimationsOfType(0,1,5,6)`.**
- **SetMenuEnabled** — if disabling: MenuDown then flag=0; if enabling: flag=1 (no forced MenuUp).

### 4.3 State flags

- **SetFlags(flags)** `0x0066C0E0` (BE): `0`→no-op; `0x10`→dispatch m_pObj18 `+0x50`(1) return;
  `0x100`→dispatch `+0x50`(0) return; else OR bits into m_flags, then if bit `0x8` set **and** menu
  up → MenuDown.
- **ClearFlags(flags)** `0x0066C160` (BE): `0`→no-op; `0x10`→`+0x50`(0); `0x100`→`+0x50`(1); else
  clear bits.
- **IsStateSet(mask)** `0x0066C0C0` (BE): all bits of mask set in m_flags.
- **SetStanding(b)** → SetFlags(0x1) if truthy else ClearFlags(0x1). **SetInitiative(b)** → SetFlags/
  ClearFlags(0x20).

### 4.4 Position-zoom table

- **AddPositionZoom(name, value, zoomName)** `0x0066C530` (BE): append only if name not already
  present (GetPositionZoom == sentinel); grow array; dup strings; increment count.
- **GetPositionZoom(name)** `0x0066C690` (DE): linear search → value, else default sentinel `*0x00888EB4`.
- **GetPositionLookAtName(name)** `0x0066C720` (DE): as above → look-at name (`+0x08`) or null.

### 4.5 Phonemes

- **AddPhoneme(key, name)** `0x00668F60` (LV): no-op unless the phoneme guard (`+0x180`) is non-null;
  else insert/replace in the phoneme hash (`+0x184`).

### 4.6 Status system

- **SetStatus(a0..a3, key)** `0x00669D10` (LV, SEH): key>5 → return; lazily create `m_pStatusUI` via
  `Bridge.BridgeMenus.CreateCharacterTooltipBox(self)`; get-or-create the key's widget; position it.
- **GetStatus(key)** `0x00669CC0` (BE): status-hash lookup → value or 0.
- **ClearStatus(key)** `0x00669F70` (LV): key 0..5; unlink+destroy the node; refresh the UI.

### 4.7 Body / head morphology

- **GetHeadHeight** `0x006692A0` (BE): resolve+validate `"Bip01 Head"` bone; return height `+0x90`
  or sentinel `*0x00888B54`. **MorphBody(scale, headNameOverride)** `0x00667E10` (LV): store a morph
  value at the bone's `+0x60`.

### 4.8 Animation queue (internal machinery)

Doubly-linked list of queue nodes over a slab freelist. Records carry the scene object, flags to
apply, a category code, an optional name.

**Record-release idiom:** free the record name buffer, free the record; when releasing the *current*
animation, first resolve its live object and Skip/Stop it.

- **SetCurrentAnimation(a, b, c, d)** `0x0066AEF0` (LV, SEH). Enqueue, resolving conflicts:
  1. Alloc a 0x10 record; `obj = a ? *(a+4) : 0`, flags `= c`, category `= b`, name `= dup(d)` (null
     if d null).
  2. Classify the new record vs the **current** animation (`Classify1`, `0x0066C9E0`): result 0/1 →
     stop the current's object; result 2/1 → **reject** (stop `a`'s object, free the new record,
     return).
  3. Walk every queued node; classify vs the new one (`Classify2`, `0x0066C860`): 0/1 stops that
     queued animation's object; 2/1 rejects as above.
  4. Pop a freelist node, append at the tail, store the record, increment count.
  > `Classify1`/`Classify2` codes: 0=stop-existing, 1=stop-both-and-reject, 2=reject-new,
  > else=coexist. **The exact conditions are RE-confirmed in the SP2 spec §5 (the 7×7 verdict
  > table)** — `Classify1` is `Classify2` run with the current animation as "existing"; categories
  > drive it; names tiebreak only cells (3,4) and (5,6); flags word and object identity are ignored.
- **ClearAnimationsOfType(cat)** `0x0066AE50` (LV): walk the queue; for each record of that category,
  resolve its live object and Skip it (a marking/skip pass, not an unlink).
- **ClearExtraAnimations** `0x0066AAB0` (BE): `ClearAnimationsOfType(0); (1); (5); (6)`.
- **ClearAnimations** `0x0066A7F0` (LV): full hard-reset — drain the queue (unlink, recycle, stop
  object, release idiom); free+null `m_pLocName`/`m_pTargetName`; clear the speak queue; clear the
  three list blocks; nudge the anim factory; free the position records + array.
- **ReleaseCurrentAnimation(param2)** `0x0066D270` (BE): if `m_pCurAnim` null return; if the current
  animation's live object completed (`Fn006F0EE0` on its object returns null) → run OnAnimRelease,
  release idiom, null `m_pCurAnim`. If param2 non-null: if the record's object matches `*(param2+4)`,
  release and return.
- **OnAnimRelease(rec)** `0x00669480` (BE): category 6 (glance-away) → free+null `+0xa4`, clear bit
  0x2; category 4 (turn-back) → free+null `+0xa0`, clear bit 0x4.
- **UpdateAnimationQueue** `0x006694F0` (BE) — per-tick driver:
  1. `ReleaseCurrentAnimation(0)`. If still current, or queue empty, return.
  2. Pop the head node (recycle; transfer record to become `m_pCurAnim`); maintain head/tail/count.
  3. Dispatch by category: `4` → Special4 (if it declines, stop the record's object); `6` → Special6
     (else stop); otherwise resolve the object; if ShouldPlayNow → PreparePlay + Play, else Stop.
  4. Set `m_pCurAnim` = record. If this character is the current tooltip owner and bit 0x8 set, call
     `BridgeHandlers.DropCharacterToolTips`.
- **Special4(rec)** `0x0066BC40` / **Special6(rec)** `0x0066B8C0` (BE) — "compose a follow-up and
  chain it": guard on the relevant name field (`+0xa0` for Special4, `+0xa4` for Special6); compose a
  name (`"%sBack%s"` / `"%sGlanceAway%s"` from `m_pLocName` and that field); build via `m_pAnim->Make`
  + CallPythonAnimationFactory. If that fails, return 0 (declined). Resolve the record's live object:
  if none, just play the new animation and return 0; otherwise chain the new animation onto it
  (`0x007007F0`) and play, returning 1 (handled).
- **ShouldPlayNow(rec)** `0x00669300` (BE): category 2 always plays; a pending move-target (`+0xa0`
  set) blocks anything except category 4; with no glance-target (`+0xa4`==0) it plays; categories 6
  and 3 play; otherwise defer. Returns 1/0.
- **PreparePlay(rec)** `0x00669350` (BE): `SetFlags(rec.flags)`; if category 3: dup the record's name
  into `+0xa0` (move target), and if bit 0x2 is set free+null `+0xa4` and clear bit 0x2; if category
  5: dup the record's name into `+0xa4` (glance target).

### 4.9 Predicates

- **IsAnimating** `0x0066A580` (BE): true if `m_uiCount>0`; else `ReleaseCurrentAnimation(0)` and
  whether the current's live object is still active.
- **IsGoingToAnimate** `0x0066A5C0` (BE): whether the next-animation pointer (`+0x160` in this view)
  is non-null.
- **IsAnimatingInterruptable** `0x0066A5D0` (LV): `ReleaseCurrentAnimation(0)`, then true iff the
  current (if any) **and** every queued animation are interruptable (∈ {0,1,5,6}).
- **IsAnimatingNonInterruptable** `0x0066A630` (LV): `ReleaseCurrentAnimation(0)`, then true iff the
  current is category 2, **or** any queued record is category 2.

### 4.10 Playback & high-level actions

Compose an animation (often via the Python factory), attach an optional completion event, enqueue via
SetCurrentAnimation. Completion-event attachment is `event->m(target)` at `0x006FE760`.

- **CallPythonAnimationFactory(nameArg)** `0x0066B290` (LV): null → null; copy name; **split at the
  LAST `.`** into module/func; fetch Python `self` (vtable `+0x20`); `TG_CallPythonFunction(module,
  func, "O", &result, "(O)", self)`; on `-1` clear error + null; else unwrap `result` + return.
- **SetAnimationDoneEvent(a1, a2)** `0x0066AE90` (BE): create a done action (0x2C), handler id
  `+0x10 = 0x80004A`, bind to this + a1, store a2 at `+0x28`, register on a1.
- **PlayAnimation(name, mode, pDoneEvent)** `0x0066BE00` (BE): null name → false; build
  `CallPythonAnimationFactory(m_pAnim->Make(name))`, null → false; attach done event; dispatch by
  mode — `mode>0`: `SetAnimationDoneEvent(anim,0)`, `SetCurrentAnimation(anim,1,0,0)`; `mode<0`:
  `SetCurrentAnimation(anim,2,0,0)`; `mode==0`: `SetAnimationDoneEvent(anim,0x800)`,
  `SetCurrentAnimation(anim,2,8,0)`. Return true.
- **PlayAnimationFile(filename, mode, pDoneEvent)** `0x0066BEB0` (BE): build a `TGAnimAction`
  + `TGSequence`; `mode==0` → done 0x800 + `SetCurrentAnimation(seq,2,8,0)`; else done 0 +
  `SetCurrentAnimation(seq,1,0,0)`.
- **Breathe(param2)** `0x0066BD10` (BE): only when idle (not animating, no next animation, neither bit
  0x4 nor 0x2 set); compose `"%sBreathe"` from `m_pLocName`, build; on fail retry bare `"Breathe"`;
  on fail return false; attach done(0) + optional completion; `SetCurrentAnimation(anim,0,0,0)`; true.
- **GlanceAt(name, completedEvent)** `0x0066B760` (BE): null → false; compose `"%sGlance%s"`; build;
  `SetAnimationDoneEvent(anim,0)`; optional attach; clear `0,1`; `SetCurrentAnimation(anim,5,2,name)`;
  true.
- **GlanceAway(completedEvent)** `0x0066B840` (BE): `m_uC0=0xC0000000`; bare `TGSequence`;
  `SetAnimationDoneEvent(seq,0x200)`; optional attach; clear `0,1`; `SetCurrentAnimation(seq,6,0,0)`;
  true.
- **TurnBack(completedEvent)** `0x0066BBA0` (BE): `m_uC0=0xC0000000`; `TGSequence`;
  `SetAnimationDoneEvent(seq,0x400)`; optional attach; clear `0,1,5,6`; `SetCurrentAnimation(seq,4,0,0)`;
  true.
- **TurnTowards(name, arg2)** `0x0066B990` (BE): acts only when name non-null, active, and
  `name=="Captain"` (else false). Build a `TGSequence` + two `CharacterAction`s (tags `0x19` then
  `0x1A`, second weighted 0.5); play. **Always returns false.**
- **MoveTo(destName, completedEvent)** `0x0066B680` (BE): null → false; compose `"%sTo%s"`; build via
  `m_pAnim->Make` + CallPythonAnimationFactory; null → false; `SetFlags(0x8)`;
  `SetAnimationDoneEvent(result, 0x800)`; optional attach; `SetCurrentAnimation(result, 2, 8, 0)`; if
  m_pObj18 present dispatch its `+0x50`(0); true.
- **SetLocation(name)** `0x0066B3D0` (LV): SetLocationName; Python bridge
  `Bridge.Characters.CommonAnimations.SetPosition(self)`; drain the queue; release current unless
  category 2; re-init the location node; free+null `+0xa0`/`+0xa4` + clear bits 0x4/0x2; finalize.

### 4.11 Speaking & sound

- **IsSpeaking / IsReadyToSpeak** — forward to the speak queue. **IsSomeoneSpeaking** `0x00666F00`:
  global active-speaker count (`0x00991F34`) > 0.
- **AddSoundToQueue(pSound, type, data)** `0x0066CB90`: no-op unless speak queue + pSound present; if
  type==2 and ready/speaking, play immediately (vtable `+0x50`); else enqueue.
- **SpeakHelper / SpeakLine / SayLine** — build a `TGSequence` of `CharacterAction`s; clear the
  interruptable set (`0,1,5,6`); play.

### 4.12 Context menu

- **MenuUp** `0x0066CDF0` (LV): requires a menu-state object, bit 0x8 NOT set, the m_pObj18 veto
  predicate (slot `+0x54`) not vetoing, `m_bMenuEnabled` set, and the menu-state ready flag (`+0x28`
  bit 0x1). Build+submit+activate a menu action; return whether the menu is up.
- **MenuDown** `0x0066CEA0` (BE): if no menu-state return false; build+submit+activate; return whether
  down. **GetCharacterFromMenu(menuId)** static — binary-search the "bridge" set; first member whose
  `+0x14c` == menuId.

### 4.13 Set / registry statics

- **GetObjectsInSet(pSet, pOut)** `0x00666D90` (BE): enumerate members of class ID `0x8016`.
- **GetObject(arg1, arg2)** `0x00666E50` (BE): if arg1 non-null, `Cast(0x8016, arg2)`; else iterate
  the registry in **reverse**, first non-null cast.
- **RegisterEventHandlers / RegisterHandlerDebugNames** — register the animation-done handler
  (`0x80004A`) and the menu handler (`0x0080004C`).

## 5. Cross-cutting idioms

- **String setters** — free-old / dup-new / null-clear.
- **Python-bridge** — call + DECREF(arg) + DECREF(result) + error-clear on `-1`.
- **Record-release** — free record name, free record, stop/skip live object.
- **Anim-queue node** — pop from freelist / append at tail / recycle; slab blocks of `m_nPerBlock`.
- **Hash-map get-or-create** — `hash(key)` bucket, `compare` walk, insert-at-head with count bump.
