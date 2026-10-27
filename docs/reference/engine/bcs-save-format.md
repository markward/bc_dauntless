# Bridge Commander Save Format (.BCS)

Reference for the on-disk format produced by `stbc.exe` / `Appc.dll` via
`g_kUtopiaModule.SaveToFile(filename)` (SDK: [`MissionLib.SaveGame`](../../../sdk/Build/scripts/MissionLib.py)
→ `App.g_kUtopiaModule.SaveToFile`). The current project's headless
Phase 1 shim ([engine/appc/save_load.py](../../../engine/appc/save_load.py))
emits a small JSON file with the same `.BCS` extension; **that JSON is
not what the real engine writes**. This doc is exclusively about the
real binary format.

Companion tool: [`tools/bcs_inspect.py`](../../../tools/bcs_inspect.py)
parses every region documented here and reports the boundary of the
still-undecoded middle.

Sample used to derive this document:
`game/saves/C-E8M1-Mark.BCS` — 1,920,656 bytes, Episode 8 Mission 1,
21 game-objects alive, 12,449 pickle-memo entries.

---

## File layout

```
+-----------------------------------------------------+
| 0x0000  Preamble (UtopiaSV)            ~165 bytes  |  6.4%  ✅ decoded
+-----------------------------------------------------+
| 0x00a1  Object table (21 × 33-byte)     693 bytes  |        ✅ decoded
+-----------------------------------------------------+
| 0x0357  TGL inventory (24 entries)      870 bytes  |        ✅ decoded
+-----------------------------------------------------+
| 0x06bd  Object-state region           1,798,144 B  | 93.6%  ❌ open
|         (binary + embedded pickle fragments)        |
+-----------------------------------------------------+
| 0x1b76bd Pickle memo run              120,787 B    |  6.3%  ⚠️ structurally
|          (12,449 alternating id/value blobs)        |        decoded;
+-----------------------------------------------------+        semantics open
```

All multi-byte integers and floats are **little-endian**. All "Pascal
strings" are `uint32 length` + that many raw bytes (length includes the
trailing NUL).

---

## Preamble (UtopiaSV) — fully decoded

| Offset | Size | Field |
|---|---|---|
| 0 | pstr | Magic. Always `"UtopiaSV"` (length 9, includes NUL) |
| 0x0d | `<7f 2i>` (36) | UtopiaModule scalars (see below) |
| 0x31 | 24 | Zero padding |
| 0x49 | pstr | Campaign name — e.g. `"Maelstrom"` |
| 0x57 | pstr | Install dir — e.g. `"C:\Program Files\Activision\Bridge Commander"` |
| 0x88 | pstr | Build dir — e.g. `"D:\Build"` (the SDK's compile-time path, leaked verbatim into every save) |
| 0x95 | 8 | Zero padding |
| 0x9d | `<I>` | Object-id high-water mark (next-id allocator) — `0x163934` in the sample |

The 9-value scalar block at 0x0d:

| Index | Type | Sample | Likely meaning |
|---|---|---|---|
| 0 | float | 1.0048 | Save-format / game version |
| 1 | float | 5000.0 | `friendly_fire_max` |
| 2 | float | 0.0 | `friendly_fire` (accumulator) |
| 3 | float | 300.0 | `friendly_fire_warning_points` |
| 4 | float | 0.0 | `friendly_tractor_time` |
| 5 | float | 15.0 | unknown timer/cooldown |
| 6 | float | 60.0 | unknown timer/cooldown |
| 7 | int32 | 300 | unknown count |
| 8 | int32 | -1 | unknown sentinel (probably "no slot selected") |

The mapping to `MissionLib.UtopiaModule` attributes is informed by
`engine/appc/save_load.py`'s field set, but indices 5–8 are not yet
positively identified.

---

## Object table — fully decoded

A contiguous run of fixed 33-byte records introduced by the literal tag
`01 03 01 00 00`. The walk ends when the next 5 bytes don't match the
tag (followed by a single zero separator before the TGL count).

Per-record layout (28-byte body after the 5-byte tag):

```c
struct ObjectTableRecord {
    uint8  tag[5];        // 01 03 01 00 00
    uint32 id;            // object's g_iObjectID; always < id_hwm
    float  f0, f1;        // usually (0.0, 0.0); occasionally (0.5, -1.0) etc.
    float  g0, g1;        // usually equal; values ~19–24 ("ship radius m"?)
    uint32 prev_id;       // = id - 1 in EVERY observed sample
    uint32 next_id;       // graph edge to another id in the same table
};
```

Observed invariants across the sample (21 records):

- `prev_id == id - 1` for every record. Probably the just-previously-
  allocated id; it isn't a linked-list traversal pointer.
- `next_id` references another record in the table (or 0); ordering is
  not lexicographic by id.
- One record has `id = 6` (much smaller than the rest) with distinctive
  `(0.5, -1)` floats and `g_pair = (4000.282, 4000.282)`. Probably a
  special anchor (camera? sun? scene root?), not a ship-class object.

---

## TGL inventory — fully decoded

```c
struct TGLInventory {
    uint32 count;             // 24 in the sample
    struct {
        pstr   path;          // e.g. "data/TGL/Ships.tgl"
        uint32 refcount;      // 0..20 observed
    } entries[count];
};
```

The `refcount` is plausibly the number of TGL records the engine pulled
from that file during the save (loaded ships use Ships.tgl heavily ⇒
high count; rarely-touched files have count 0). Confirming this is a
Phase 2 instrumentation question.

The path list reveals the loaded campaign/mission unambiguously —
e.g. `data/TGL/Maelstrom/Episode 8/E8M1.tgl` with refcount 20
identifies this as an in-progress E8M1 save.

---

## Pickle memo run — structurally decoded, semantically open

The last 120,787 bytes of the file are **12,449 back-to-back Python
pickle protocol-1 blobs** averaging 9.7 bytes each. Every blob is a
complete pickle stream terminated by `.` (STOP, `0x2e`).

They come in alternating pairs:

```
BININT2(n)            STOP        # 4 bytes  — "next memo slot is n"
SHORT_BINSTRING(...)  STOP        # variable — the value at slot n
```

Other observed value-side opcodes include `GLOBAL` (class import), `NONE`,
and `LONG_BINGET` (memo backreference). Sample value strings include
property names (`sLastSubsystemChangeEvent`, `_19f49c00_p_TGBoolEvent`,
`sVersion`), version strings (`20070204`), and class identifiers
(`Custom.Autoload.000-Fixes20040612-LCBridgeAddon types`).

**Conclusion:** this region is the C++ engine's externalised pickle
**memo table** — a flat (id → value) lookup that the binary middle
region almost certainly indexes into when it needs to reference a string
or class without duplicating it. This decoupling is consistent with how
Appc threads Python state across many objects without explosive
duplication.

What's *not* known: which memo ids the binary middle actually
dereferences, and whether the memo is laid out in allocation order or in
some other walk order.

---

## Object-state region — outstanding work ❌

**1,798,144 bytes — 93.6% of the file — and almost entirely undecoded.**

The region starts at 0x06bd and ends at 0x1b76bd (where the pickle memo
run begins). It contains:

- A **36-byte header** for the player ship (the very first entry, no type
  tag), beginning with `float radius`, `uint32 self_id` (0x927d in the
  sample), `uint32 target_or_parent_id` (0x994c), `uint32 count_or_flags`,
  `float range`.

- ~4,543 **type-tagged entries** at 4-byte-aligned offsets, introduced by
  a 4-byte type tag of the form `XX 01 00 00` (the trailing `01 00 00` is
  uniform; the first byte varies).

- **Embedded strings** in two encodings: UTF-8 (`"Warp Core"`) and
  UTF-16LE (`"Galaxy"`, `"Beams"`, `"Torpedo"`). Why both is not yet
  clear — it may reflect different string-class identities on the C++
  side (`std::string` vs. `TGString`).

- **Object-id cross-references**: each of the 15 (of 21) table-object ids
  that appear in this region appears **exactly once** as a uint32. The
  remaining 6 object ids (0x919f, 0x9645, 0x9837, 0x9885, 0x9909, 0x9a58)
  don't appear at all — those objects' state must live elsewhere
  (presumably entirely in the pickle memo).

### Type-tag distribution

`bcs_inspect.py` (instrumented variant) found these 4-byte-aligned
type-tag occurrences in the sample save:

| Tag (1st byte) | Count | Likely semantic |
|---|---|---|
| `0x08` | 1,115 | Dominant. Most are 32 bytes. Subsystem-level state? |
| `0x35` | 220 | Frequent. Size unknown. |
| `0x3f` | 212 | Frequent. Size unknown. |
| `0x07` | 122 | Common. Some 32-byte. |
| `0x01` | 241 | |
| `0x3e` | 12 | |
| `0x10` | 8 | |
| `0x04` | 8 | |
| 16 others | ≤ 5 each | Rare types — probably scene-singleton state |

Entry-size histogram (gap between consecutive type tags) is dominated by
**36 bytes** (1,342 entries), with secondary peaks at 60, 32, 40, 28,
and 44.

### What's needed to fully decode this region

1. **Identify the canonical per-object entry boundary.** Walking forward
   from 0x06bd, we'd like to know where each `ObjectClass` (or
   `PhysicsObjectClass`, `ShipClass`, `DamageableObject`) record begins.
   Hypothesis: each starts with its own object-id (uint32) and ends just
   before the next id from the object table. Needs verification on
   multiple saves.

2. **Decode the type-0x108 entry** (1,115 instances at 32 bytes — the
   largest contiguous block). Cross-reference its embedded uint32 fields
   against known object ids and the SDK's `__getstate__` implementations
   (39 classes; see `CLAUDE.md` key facts). High-leverage target.

3. **Distinguish "real" type tags from incidental `XX 01 00 00`
   byte-coincidences.** The 0x00-tag count of 2,561 is mostly false
   positives (zeros next to a stray `01`). Tag validation likely requires
   knowing the preceding entry's size.

4. **Map the embedded pickle fragments to their memo references.** If we
   confirm the binary middle uses `LONG_BINGET`-style memo indices to
   pull values from the trailing memo run, we can recover strings and
   class refs without duplicating them.

5. **Cross-save diff.** Re-run `bcs_inspect.py` on a smaller `Captain
   Save-*.BCS` and the early-mission `C-E2M2-Picard.BCS` etc., and diff
   the regions to see what scales with ship loadout vs. mission state.
   This narrows what each chunk represents.

6. **Static analysis of `Appc.dll`'s `SaveToFile`.** The decoding rules
   live in the C++ binary. A focused IDA/Ghidra pass on `SaveToFile` and
   its callees in `stbc.exe` would resolve all of the above in a
   structured way and is probably the highest-leverage approach.

### Why this is open work, not blocking

Phase 1 and Phase 2 do not need to **read** real BCS saves — both rely
on the project's JSON shim for any save/load functionality. The real
binary format is interesting for:

- **Lossless migration**: letting players bring their original
  Bridge Commander save games into the reimplemented engine.
- **Cross-validation**: comparing a captured pre-save game state against
  what the project's headless harness would have produced.
- **Reverse-engineering insight**: the format encodes engine
  assumptions about object lifetime, identity, and Python ↔ C++ state
  ownership that no other reference makes explicit.

None of these are on the Phase 2 critical path. Treat this as a
parking-lot RE task to be picked up when motivated.

---

## Reproducing

```bash
uv run python tools/bcs_inspect.py                       # uses sample save by default
uv run python tools/bcs_inspect.py path/to/your.BCS      # other save
uv run python tools/bcs_inspect.py --records 25 --blobs 50   # more verbose
uv run python tools/bcs_inspect.py --pickle-out memo.pkl # dump trailing memo
```
