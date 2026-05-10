# C++ Runtime: Type Info, Vtables, and Class Hierarchies

Reference for the C++-side runtime in `stbc.exe`: how the binary identifies
classes (without MSVC RTTI), what the vtables actually look like for the
NetImmerse, TG-framework, and BC game-object hierarchies, and where the
key entry points live in the binary.

---

## No MSVC RTTI for engine classes

The binary was compiled with `/GR-` (RTTI disabled) for engine and game
code. The `.data` segment contains exactly **22 standard MSVC
`TypeDescriptor` structures**, *all* of them belonging to the C++ Standard
Library — `std::ios_base`, `std::basic_istream<char>`, `std::exception`,
`std::bad_alloc`, `type_info` itself, and so on. Their addresses are
catalogued in the source repo; for our purposes the relevant facts are:

- The only game-specific class with MSVC RTTI is `TGStreamedException`
  (throw type `.PAVTGStreamException@@` at `0x0095AD10`), used so
  `throw`/`catch` works.
- Everything else uses one of two custom type-info systems:
  1. **NetImmerse NiRTTI** — a factory/registration table (described
     below) used by every `Ni*` class.
  2. **SWIG 1.x Python binding tables** — `ClassName_MethodName`
     wrapper functions that double as a class catalogue. The bindings
     also embed a per-class string identity used for SWIG type checks.

Class-name strings in the binary (about 1,179 of them, referenced from
code) come predominantly from these two systems.

---

## NiRTTI factory

### Hash table

A single global hash table at `DAT_009a2b98` indexes class-name strings
to factory functions. It is created on first registration, then shared
by every subsequent `Ni*` class as well as the two `TG*` classes that
register through the same path (`TGDimmerController`,
`TGFuzzyTriShape`).

```
0x009a2b98  NiRTTI hash table pointer
            +0x00  vtable pointer (PTR_FUN_0088b7c4)
            +0x04  entry count
            +0x08  bucket count                  = 0x25 (37, fixed)
            +0x0C  bucket array (37 × 4 = 0x94 bytes)
```

Bucket nodes are 12-byte linked-list cells:

```
+0x00  className (char*)
+0x04  factory function pointer
+0x08  next (or NULL)
```

The hash-table object has a tiny vtable at `PTR_FUN_0088b7c4` whose
slots are:

| Offset | Operation                                                 |
|--------|-----------------------------------------------------------|
| `+0x04`| `hash(className) -> bucket_idx`                            |
| `+0x08`| `compare(className, node->className) -> bool`              |
| `+0x0C`| `setEntry(node, className, factoryFn)`                     |
| `+0x10`| `deleteEntry(node)` — clears node fields                   |

### Registration pattern

Every registered class has its own one-shot registration function that
follows an identical template (here for `NiNode`, registration at
`FUN_007e3670`):

```c
if (g_alreadyRegisteredFlag) return;
g_alreadyRegisteredFlag = 1;

if (g_NiRTTITable == NULL) { /* allocate the table on first use */ }

bucket = hash("NiNode");
node = buckets[bucket];
while (node) {
    if (compare("NiNode", node->className)) {
        deleteEntry(node);
        setEntry(node, "NiNode", FUN_007e5450);  /* factory */
        return;
    }
    node = node->next;
}
newNode = NiAlloc(0x0C);
setEntry(newNode, "NiNode", FUN_007e5450);
newNode->next = buckets[bucket];
buckets[bucket] = newNode;
count++;
```

Each registration owns a guard byte in `.data` (e.g. `DAT_009a18a0`
for `NiNode`); the registration function bails early on the second
call.

### Consumer

Two callers walk the table to deserialise `Ni*` objects out of NIF
streams:

| Address       | Function              | Role                                                    |
|---------------|-----------------------|---------------------------------------------------------|
| `FUN_008176B0`| `NiStream::LoadObject`| Reads class name from stream, looks up factory, invokes |
| `FUN_00818150`| Alternative load path | Same lookup pattern                                      |

Failure path emits the literal *"NiStream: Unable to find loader for…"*.

### What gets registered

117 classes in total — 113 `Ni*` classes plus
`TGDimmerController` and `TGFuzzyTriShape` (the two TG classes that
participate in NIF serialisation).

Classes that never appear in `.nif` files are *absent* from the
factory table even when they have NiRTTI strings:

- Runtime-only renderers (`NiD3DRender`, `NiDDImage`, `NiDDBufferImage`)
- Audio: `NiSoundSystem`, `NiSource`, `NiListener`, `NiProvider_Info`
- Runtime helpers: `NiCloneExtraData`
- Every game-specific class (`Ship*`, `TG*` UI, `ST*`, etc.)

The factory table is therefore the right reference for "what can come
out of a NIF file"; the broader RTTI string catalogue (below) is the
right reference for "what classes exist in the binary".

### Memory allocator

`NiAlloc` is `FUN_00718CB0` — a small-object pool (≤ 0x80 bytes) with a
4-byte size header, falling back to `malloc` for larger allocations.

---

## NetImmerse class hierarchy

The engine uses NetImmerse 3.1.x (the predecessor of Gamebryo). The
binary identifies itself as NIF version 3.1 in NIF format terms; both
`V3_0` and `V3_1` are tagged as "Star Trek: Bridge Commander" in
nif.xml, and both are marked `supported="false"` (NifSkope cannot open
them) but their fields are documented.

### Constructor chain

Each constructor calls its parent, initialises its own fields, then
overwrites the vtable pointer. The final write is the runtime vtable.

```
FUN_007D87A0  NiObject ctor       → vtable 0x00898B94
  FUN_007DAC80  NiObjectNET ctor  → vtable 0x00898C48
    FUN_007DC0C0  NiAVObject ctor → vtable 0x00898CA8
      NiNode  factory FUN_007E5450 → vtable 0x00898F2C
      NiGeometry ctor FUN_007EDD10 → vtable 0x00899164
        NiTriShape ctor FUN_007EF260 → vtable 0x00899264
```

### Vtable summary

| Class        | Vtable     | Slots | Object size | Factory      |
|--------------|------------|-------|-------------|--------------|
| `NiObject`   | `0x00898B94` | 12 (0–11)  | 0x08  | `FUN_007D8650` (registration) |
| `NiObjectNET`| `0x00898C48` | 12 (0–11)  | 0x14  | `FUN_007DAB30` (registration) |
| `NiAVObject` | `0x00898CA8` | 39 (0–38)  | 0xC4  | `FUN_007DBF70` (registration) |
| `NiNode`     | `0x00898F2C` | 43 (0–42)  | 0xE8  | `FUN_007E5450`                |
| `NiGeometry` | `0x00899164` | 64 (0–63)  | 0xE0  | (abstract — slot 49 is `__purecall`) |
| `NiTriShape` | `0x00899264` | 68 (0–67)  | 0xE4  | `FUN_007F31F0`                |

Notes on inheritance:

- `NiObjectNET` adds **no** new virtuals over `NiObject` — it just
  overrides existing ones to handle the additional fields it carries.
- `NiAVObject` adds 27 new slots (12–38) over `NiObjectNET`.
- `NiNode` adds 4 new slots (39–42) over `NiAVObject`. The Gamebryo
  1.2 source declares 5 (`AttachChild`, `DetachChild`, `DetachChildAt`,
  `SetAt`, `UpdateUpwardPass`); NI 3.1 has the first four — the fifth
  was added later or merged into another slot.
- `NiGeometry` adds 25 slots (39–63) over `NiAVObject` — substantially
  more than Gamebryo 1.2 documents.
- `NiTriShape` adds 4 slots (64–67) over `NiGeometry`.

### NiObject vtable layout (12 slots)

This is the canonical layout shared by every `Ni*` class. **The MSVC
scalar-deleting destructor is at slot 10 in NI 3.1, not slot 0** — in
Gamebryo 1.2 it's the other way around. `GetRTTI` occupies slot 0.

| Slot | Offset | Method                  | Behaviour (NiObject base / NiObjectNET override)                           |
|------|--------|-------------------------|----------------------------------------------------------------------------|
| 0    | `+0x00`| `GetRTTI`               | Returns the static NiRTTI pointer (NiObject's lives at `0x009a1468`)       |
| 1    | `+0x04`| `CreateClone`           | Overridden in every derived class                                          |
| 2    | `+0x08`| `ProcessClone`          | NiObjectNET clones `ExtraData` (this+0x10)                                 |
| 3    | `+0x0C`| `PostLinkObject`        | NiObjectNET processes `TimeController` (this+0x0C)                         |
| 4    | `+0x10`| `RegisterStreamables`   | Stream hash-table registration                                              |
| 5    | `+0x14`| `LoadBinary`            | Empty in `NiObject`; reads name + extras in `NiObjectNET`                  |
| 6    | `+0x18`| `LinkObject`            | Resolves cross-references after load                                        |
| 7    | `+0x1C`| `SaveBinary`            | Calls `GetRTTI` (slot 0), writes class name then object index              |
| 8    | `+0x20`| `IsEqual`               | Compares RTTI names then class-specific data                                |
| 9    | `+0x24`| `AddViewerStrings`      | `"m_iRefCount"` for NiObject; name/controllers/extradata for NiObjectNET   |
| 10   | `+0x28`| `scalar_deleting_dtor`  | Pattern: `realDtor(); if (param & 1) free(this);`                           |
| 11   | `+0x2C`| (no-op)                 | Always `0x0040DA50`; never overridden anywhere in the hierarchy            |

NI 3.1 vs Gamebryo 1.2 slot order — the difference is enough to break
any code that walks the vtable assuming Gamebryo layout:

| NI 3.1 slot | Method                     | Gb 1.2 slot |
|-------------|----------------------------|-------------|
| 0           | `GetRTTI`                  | 1           |
| 1           | `CreateClone`              | 2           |
| 2           | `ProcessClone`             | 10          |
| 3           | `PostLinkObject`           | 11          |
| 4           | `RegisterStreamables`      | 5           |
| 5           | `LoadBinary`               | 3           |
| 6           | `LinkObject`               | 4           |
| 7           | `SaveBinary`               | 6           |
| 8           | `IsEqual`                  | 7           |
| 9           | `AddViewerStrings`         | 9           |
| 10          | `scalar_deleting_dtor`     | 0           |
| 11          | (no-op / GetViewerStrings) | 8?          |

### NiNode-specific slots (39–42)

Always reachable via fixed vtable offsets; useful to know directly:

| Slot | Offset | Method                                  | Notes                                  |
|------|--------|-----------------------------------------|----------------------------------------|
| 39   | `+0x9C`| `AttachChild(NiAVObject*, bool atEnd)`  | Sets `child->parent`; appends to array |
| 40   | `+0xA0`| `DetachChild(NiAVObject*)`              | Linear search and remove               |
| 41   | `+0xA4`| `DetachChildAt(uint index)`             | Removes index, clears child's parent   |
| 42   | `+0xA8`| `SetAt(uint index, NiAVObject*)`        | Replaces child at index                |

Slot 22 (`+0x58`) is `GetObjectByName` — base implementation in
`NiAVObject` does a `strcmp` against `this->name`; `NiNode` overrides
to recurse into children.

### Field offsets

The MWSE (Morrowind Script Extender) reverse-engineered headers are
the closest match. NI 3.1 and NI 4.0.0.2 share identical struct sizes
(verified via MWSE `static_assert`s):

| Class         | Size  | Notes                                                    |
|---------------|-------|----------------------------------------------------------|
| `NiObject`    | 0x08  | vtable + refcount                                        |
| `NiObjectNET` | 0x14  | + `name` (+0x08), `extraData` (+0x0C, single ptr), `controllers` (+0x10) |
| `NiAVObject`  | 0x90  | + flags (+0x14), parent (+0x18), worldBound (+0x1C), localRotation (+0x2C), localTranslate (+0x30), localScale (+0x3C), worldTransform (+0x40), velocities (+0x74), modelABV (+0x78), worldABV (+0x7C), collideCallback (+0x80), propertyNode (+0x88) |
| `NiNode`      | 0xB0  | + children (`NiTArray`, +0x90), effectList (+0xA8)        |

Note that **Gamebryo 1.2 sizes are larger** because the `m_pkExtra`
single-pointer became an array (+8 bytes on `NiObjectNET`) and a
`m_spCollisionObject` was added (+4 bytes on `NiAVObject`). Do not
copy-paste Gb 1.2 offsets; methods are usable but the layouts differ.

### NIF format quirks (V3.1)

A handful of fields exist only in V3.1 or were removed shortly after.
The most consequential for asset reading:

- `NiObjectNET.ExtraData` is a **single `Ref` pointer** (linked list
  through `m_pNext`), not an array. Range `3.0 — 4.2.2.0`.
- `NiAVObject.Velocity` (Vector3) is **present** in V3.1; removed in
  Gamebryo 1.2.
- `NiAVObject.HasBoundingVolume` + `BoundingVolume` are **present** in
  V3.1; removed in Gamebryo 1.2.
- `NiAVObject.CollisionObject` is **absent** in V3.1 (added at 10.0.1.0).
- `NiTimeController.Target` (Ptr to `NiObjectNET`) is **absent**; an
  `Unknown Integer` field exists in its place (`until="3.1"`).
- `NiParticleSystemController` has **12 V3.1-only fields** that were
  removed by 3.3+.
- `NiFlipController.Images` are `NiImage` refs (replaced by
  `NiSourceTexture` after 3.1).
- `TexDesc.Image` is similarly a `NiImage` ref.

### NetImmerse class catalogue

129 unique `Ni*` classes are referenced from the binary. Highlights by
function (full string addresses are in the source repo's catalog):

- **Scene graph nodes** — `NiObject`, `NiObjectNET`, `NiAVObject`,
  `NiNode`, `NiBillboardNode`, `NiBSPNode`, `NiBone`, `NiCollisionSwitch`,
  `NiFltAnimationNode`, `NiLODNode`, `NiSortAdjustNode`, `NiSwitchNode`.
- **Geometry** — `NiGeometry`, `NiGeometryData`, `NiTriBasedGeom(Data)`,
  `NiTriShape(Data)`, `NiTriShapeDynamicData`, `NiEnvMappedTriShape(Data)`,
  `NiTriangles(Data)`, `NiTriStrip(Data)`, `NiTriStrips(Data)`,
  `NiLines(Data)`, `NiScreenPolygon`.
- **Bezier subsystem** — `NiBezierMesh`, `NiBezierPatch`, three
  `NiBezierRectangle{,2,3}`, four `NiBezierTriangle{,2,3,4}`,
  `NiBezierCylinder`, `NiBezierSkinController`. *Entire subsystem
  removed before Gamebryo 1.2.*
- **Properties** — `NiProperty`, plus `NiAlphaProperty`,
  `NiCorrectionProperty`, `NiDitherProperty`, `NiFogProperty`,
  `NiMaterialProperty`, `NiMultiTextureProperty`, `NiShadeProperty`,
  `NiSpecularProperty`, `NiStencilProperty`, `NiTextureModeProperty`,
  `NiTextureProperty`, `NiTransparentProperty`,
  `NiVertexColorProperty`, `NiWireframeProperty`, `NiZBufferProperty`.
- **Lights** — `NiLight`, `NiAmbientLight`, `NiDirectionalLight`,
  `NiPointLight`, `NiSpotLight`, `NiTextureEffect`, `NiDynamicEffect`.
- **Controllers/animation** — `NiTimeController`, `NiAlphaController`,
  `NiFlipController`, `NiFloatController`, `NiKeyframeController`,
  `NiKeyframeManager`, `NiLightColorController`, `NiLookAtController`,
  `NiMaterialColorController`, `NiMorphController`,
  `NiMorpherController`, `NiPathController`,
  `NiParticleSystemController`, `NiRollController`, `NiSkinController`,
  `NiTriShapeSkinController`, `NiVisController`.
- **Animation data** — `NiKeyframeData`, `NiFloatData`, `NiColorData`,
  `NiMorphData`, `NiPosData`, `NiVisData`, `NiAnimBlender`.
- **Extra data** — `NiExtraData`, `NiBinaryVoxelData`,
  `NiBinaryVoxelExtraData`, `NiCloneExtraData`, `NiStringExtraData`,
  `NiTextKeyExtraData`, `NiVertWeightsExtraData`,
  `NiSequenceStreamHelper`.
- **Physics/collision** — `NiForce`, `NiGravity`, `NiParticleBomb`,
  `NiSphericalCollider`, `NiPlanarCollider`.
- **Rendering/images** — `NiRender`, `NiD3DRender`, `NiImage`,
  `NiRawImageData`, `NiDDImage`, `NiDDBufferImage`, `NiCamera`,
  `NiAccumulator`, `NiAlphaAccumulator`, `NiClusterAccumulator`.
- **Audio** — `NiSoundSystem` (renamed `NiAudioSystem` later),
  `NiSource` (`NiAudioSource`), `NiListener` (`NiAudioListener`),
  `NiProvider_Info` (removed).
- **Math** — `NiPoint2`, `NiPoint3`, `NiColor`, `NiColorA`,
  `NiFrustum`, plus constants like `NiPoint2_UNIT_Y`, `NiColorA_BLACK`,
  `NiColor_WHITE`.
- **Containers** — `NiTArray`, `NiTList`, `NiTMap`. Specific
  instantiations include `NiTList<ShipSubsystem>`.
- **Smart pointers** — `NiSourcePtr`, `NiCameraPtr`, `NiSourceObj`.

### Reference-priority guide for struct annotation

In rough order of accuracy:

1. **MWSE C++ headers** (`engine/mwse/`) — identical struct sizes to
   NI 3.1, with named fields and offsets. Vtable order *does* differ
   (MWSE's NI 4.0.0.2 has the destructor at slot 0; NI 3.1 has GetRTTI
   at slot 0). Use it for *fields*, not slots.
2. **niftools `nif.xml`** — serialisation order with version-tagged
   `since`/`until` attributes. Covers 21 of 42 NI-3.1-only classes
   that aren't in Gamebryo 1.2. Documents bytes-on-disk only; not
   memory layout.
3. **Gamebryo 1.2 source** — full C++ implementations and method
   names. Offsets are shifted (+8 on `NiObjectNET`, +12 on
   `NiAVObject`); methods translate cleanly, fields don't.
4. **Ghidra binary decompilation** — ground truth, but expensive.
   Use for the 21 runtime-only classes that have no external reference.

The Gamebryo 2.6 SDK is too far diverged from NI 3.1 to help —
canonical NI classes survive but are flagged `DEPRECATED`, virtuals
multiplied, and the NI-3.1-only classes (`NiBezierMesh`,
`NiScreenPolygon`, `NiBezierTriangle*`) were not re-introduced.

---

## TG-framework class hierarchy

Bridge Commander's "TG" (Totally Games) framework sits on top of
NetImmerse and provides the gameplay-side base classes. **Crucially,
the TG vtable layout is different from the Ni one.** The destructor is
at *slot 0*, not slot 10:

| TG slot | Offset | Method                                                   |
|---------|--------|----------------------------------------------------------|
| 0       | `+0x00`| `scalar_deleting_dtor`                                   |
| 1       | `+0x04`| `GetTypeID` (returns the class's integer type ID)        |
| 2       | `+0x08`| `IsTypeID` (checks against the parameter)                |
| 3       | `+0x0C`| `DebugPrint`                                             |
| 4       | `+0x10`| `WriteToStream`                                          |
| 5       | `+0x14`| `ReadFromStream`                                         |
| 6       | `+0x18`| `ResolveObjectRefs`                                      |
| 7       | `+0x1C`| `PostDeserialize`                                        |
| 8       | `+0x20`| `InvokePythonHandler`                                    |
| 9       | `+0x24`| `GetClassName` (returns class-name string)               |
| 10      | `+0x28`| `GetSwigTypeName` (e.g. `"_p_TGObject"`)                 |
| 11      | `+0x2C`| `GetObjectPtrTypeName` (e.g. `"TGObjectPtr"`)            |

Every class in the TG hierarchy overrides slots 1, 2, 9, 10, 11 to
identify itself, so each class has its own `(typeID, className,
swigTypeName, objectPtrTypeName)` tuple.

### Inheritance chain to `Ship`

`Ship` is **not** an `NiObject` derivative. Its full chain:

```
TGObject              vtable 0x00896278  (12 slots)
 └── TGStreamedObject vtable 0x008962F4  (+ slots 12–15)
      └── TGStreamedObjectEx vtable 0x008962A8 (overrides slot 7)
           └── TGEventHandlerObject vtable 0x00896044 (+ slots 16–22)
                └── TGSceneObject vtable 0x00889708 (+ slots 21–48)
                     └── ObjectClass vtable 0x00889950 (extends ~slot 66)
                          └── PhysicsObjectClass vtable 0x00894128 (+ slots 67–81)
                               └── DamageableObject vtable 0x00893D88 (+ slots 78–91)
                                    └── Ship vtable 0x00894340 (92 slots, 21 overrides)
```

`Ship` is a 0x328-byte object with a 92-slot vtable; it *overrides*
many existing slots but does not add new ones beyond `DamageableObject`.

### Network-critical Ship slots

| Slot | Offset  | Method                       | Address      | Use                                             |
|------|---------|------------------------------|--------------|--------------------------------------------------|
| 4    | `+0x10` | `Ship::WriteToStream`        | `0x005B0F00` | Full serialize for `ObjCreate`                   |
| 5    | `+0x14` | `Ship::ReadFromStream`       | `0x005B1220` | Full deserialize from `ObjCreate`                |
| 67   | `+0x10C`| `SerializeToBuffer`          | `0x005A1CF0` | Network buffer serialise (PhysicsObject base)    |
| 68   | `+0x110`| `WriteNetworkHeader`         | `0x005A1D80` | Type ID + object ID                              |
| 69   | `+0x114`| `Ship::WriteNetworkState`    | `0x005B0D80` | Calls parent then ship-specific fields           |
| 70   | `+0x118`| `Ship::InitObject`           | `0x005B0E80` | NIF + subsystem init                              |
| 71   | `+0x11C`| `Ship::DeserializeFromNetwork`| `0x005B0DC0`| Walks `ship+0x284` subsystem list                 |
| 72   | `+0x120`| `Ship::WriteStateUpdate`     | `0x005B17F0` | Per-tick state sync (opcode `0x1C`)              |
| 73   | `+0x124`| `Ship::ReadStateUpdate`      | `0x005B21C0` | Per-tick receive                                  |
| 74   | `+0x128`| `Ship::SetModel`             | `0x005ABDA0` | Calls `DamageableObject::SetModel` + `ComputeBoundsFromGeometry` |
| 80   | `+0x140`| `Ship::RayIntersect`         | `0x005AE730` | Ray vs bounding sphere                            |
| 82   | `+0x148`| `Ship::CollisionTest_A`      | `0x005AF7D0` | Narrow collision                                  |
| 83   | `+0x14C`| `Ship::CollisionTest_B`      | `0x005AF830` | Narrow collision                                  |
| 84   | `+0x150`| `Ship::CheckCollision`       | `0x005AF890` | Full collision resolution                         |
| 85   | `+0x154`| `Ship::CollisionDamageWrapper`| `0x005B0060`| Damage from collision (relays via opcode `0x15`)  |
| 88   | `+0x160`| `Ship::SetupProperties`      | `0x005B3FB0` | Property → subsystem bindings                     |
| 89   | `+0x164`| `Ship::LinkAllSubsystemsToParents` | `0x005B3E20` | Parent/child linking                          |

### `PhysicsObjectClass` additions (slots 67–81)

These are the network-serialisation slots that all networked objects
share. Notable ones:

| Slot | Method                          | Address      | Notes                                            |
|------|---------------------------------|--------------|--------------------------------------------------|
| 67   | `SerializeToBuffer`             | `0x005A1CF0` |                                                  |
| 68   | `WriteNetworkHeader`            | `0x005A1D80` | type ID + object ID into stream                  |
| 69   | `WriteNetworkState`             | `0x005A1DC0` | pos + rot(euler) + vel + name                    |
| 70   | `InitObject` (`DamageableObject::InitObject`) | `0x005A2030` | reads species byte from stream     |
| 71   | `DeserializeFromNetwork`        | `0x005A2060` |                                                  |
| 72   | `WriteStateUpdate`              | `0x005A26C0` | base impl                                        |
| 73   | `ReadStateUpdate`               | `0x005A2BF0` | base impl                                        |
| 74   | `SetModel`                      | `0x00591B60` | `DamageableObject::SetModel`                     |
| 75   | `GetCollisionRadius?`           | `0x005910D0` | returns float constant from `[0x00888B54]`       |
| 77   | `SetTargetObject`               | `0x005A15A0` | virtual                                          |
| 78   | `UpdateAIForTarget`             | `0x005A16B0` | `Ship::UpdateAIForTarget`                        |
| 79   | `CheckCollisionRateLimit`       | `0x005A22A0` |                                                  |

### `DamageableObject` (92 slots, vtable `0x00893D88`)

| Slot | Method                       | DamageableObject | Ship          |
|------|------------------------------|------------------|---------------|
| 80   | `RayIntersect`               | `0x00594310`     | `0x005AE730`  |
| 82   | `CollisionTest_A`            | `0x00594440`     | `0x005AF7D0`  |
| 83   | `CollisionTest_B`            | `0x005945B0`     | `0x005AF830`  |
| 84   | `CheckCollision`             | `0x00594840`     | `0x005AF890`  |
| 85   | `ApplyCollisionDamage`       | `0x00593650`     | `0x005B0060`  |
| 86   | (collision-notify loop)      | `0x005935D0`     | `0x005935D0` (inherited) |
| 88   | `SetupProperties`            | `0x00591190`     | `0x005B3FB0`  |
| 89   | `LinkAllSubsystemsToParents` | `0x005911A0`     | `0x005B3E20`  |
| 90   | `scalar_deleting_dtor`       | `0x00596340`     | `0x005AC5E0`  |
| 91   | `array_deleting_dtor`        | `0x005962F0`     | `0x005ABF30`  |

`RegisterEventHandlers` (`0x00590980`) and `UnregisterEventHandlers`
(`0x005909B0`) are non-virtual helpers on `DamageableObject`.

### TG-framework class catalogue

Around 124 TG framework classes exist in the binary. The principal
ones, grouped by role:

- **Core framework** — `TGObject`, `TGEvent`, `TGEventHandlerObject`,
  `TGEventManager`, `TGSequence`, `TGCondition`,
  `TGPythonInstanceWrapper`, `TGAttrObject`,
  `TGTemplatedAttrObject`, `TGString`, `TGPoint3`, `TGColorA`,
  `TGMatrix3`, `TGRect`, `TGdb`.
- **Streams/serialisation** — `TGStream`, `TGBufferStream`,
  `TGProfilingInfo`.
- **Actions/scripting** — `TGAction`, `TGActionManager`,
  `TGMovieAction`, `TGCreditAction`, `TGOverlayAction`,
  `TGPhonemeAction`, `TGScriptAction`, `TGSoundAction`,
  `TGTimedAction`, `TGAnimAction`, `TGAnimPosition`,
  `TGConditionAction`.
- **Typed events** — `TGIEvent`, `TGBoolEvent`, `TGCharEvent`,
  `TGFloatEvent`, `TGIntEvent`, `TGKeyboardEvent`, `TGMouseEvent`,
  `TGGamepadEvent`, `TGObjPtrEvent`, `TGPlayerEvent`,
  `TGSequenceEvent`, `TGShortEvent`, `TGStringEvent`,
  `TGVoidPtrEvent`, `TGGameSpyEvent`, `TGMessageEvent`,
  `TGMusicFadeEvent`.
- **Networking** — `TGWinsockNetwork`, `TGNetwork`,
  `TGNetworkListType`, `TGNetGroup`, `TGNetPlayer`, `TGPlayerList`,
  `TGGroupPlayer`, `TGEncrypt`.
- **Network messages** — `TGMessage`, `TGAckMessage`,
  `TGBootPlayerMessage`, `TGConnectMessage`, `TGDisconnectMessage`,
  `TGDoNothingMessage`, `TGNameChangeMessage`.
- **Singletons/managers** — `TGInputManager`, `TGTimerManager`,
  `TGEventManager`, `TGMovieManager`, `TGModelPropertyManager`,
  `TGIconManager`, `TGFontManager`, `TGPoolManager`,
  `TGLocalizationManager`, `TGModelManager`, `TGUIThemeManager`,
  `TGSoundManager`, `TGAnimationManagerClass`, `TGSystemWrapperClass`.
- **UI framework** — `TGWindow`, `TGFrame`, `TGFrameWindow`,
  `TGPane`, `TGRootPane`, `TGButton`, `TGButtonBase`, `TGTextButton`,
  `TGIcon`, `TGConsole`, `TGDialogWindow`, `TGStringDialog`,
  `TGPrompt`, `TGUIObject`, `TGUITheme`, `TGParagraph`,
  `TGParagraphSoundHandler`.
- **Audio** — `TGSound`, `TGMusic`, `TGSoundRegion`, `TGRedbookClass`,
  `TGPhonemeSequence`.
- **Misc** — `TGFontGroup`, `TGIconGroup`, `TGConfigMapping`,
  `TGGroupList`, `TGStringToStringMap`, `TGLocalizationDatabase`,
  `TGTimer`, `TGPhoneme`, `TGConditionHandler`,
  `TGLocDBWrapperSerialize`/`Unserialize`.

114 of these are exposed to Python via SWIG. The largest interfaces by
method count: `TGUIObject` (94), `TGSound` (63), `TGMessage` (53),
`TGNetwork` (50), `TGInputManager` (41), `TGMatrix3` (38),
`TGBufferStream` (35), `TGPoint3` (35), `TGParagraph` (34),
`TGSoundManager` (33). Roughly 1,340 SWIG wrapper methods total.

---

## BC game-class catalogue

About 420 game-specific classes built on top of TG and NetImmerse. The
principal groups:

- **Object base** — `ObjectClass`, `BaseObjectClass`,
  `CameraObjectClass`, `ChatObjectClass`, `LightObjectClass`,
  `PhysicsObjectClass`, `ZoomCameraObjectClass`, `CollisionEvent`.
- **Ships** — `ShipClass`, `ShipSubsystem`, `HullClass`, `Cloak`,
  `CloakingSubsystem`, `ImpulseEngineSubsystem`,
  `WarpEngineSubsystem`, `InSystemWarp`, `Tractor`,
  `TractorBeamProjector`, `TractorBeamSystem`, `TractorBeamGraphic`.
- **Ship properties** (data-driven config) — `ShipProperty`,
  `HullProperty`, `ImpulseEngineProperty`, `WarpEngineProperty`,
  `CloakingSubsystemProperty`, `TractorBeamProperty`.
- **Weapons** — `Weapon`, `EnergyWeapon`, `PhaserBank`, `PhaserSystem`,
  `PulseWeapon`, `PulseWeaponSystem`, `Torpedo`, `TorpedoSystem`,
  `TorpedoTube`, `WeaponSystem`.
- **Weapon properties** — `WeaponProperty`, `EnergyWeaponProperty`,
  `PhaserProperty`, `PulseWeaponProperty`, `TorpedoSystemProperty`,
  `TorpedoTubeProperty`, `WeaponSystemProperty`.
- **Subsystems / damage** — `SubsystemProperty`, `DamageableObject`,
  `PowerSubsystem`, `PoweredSubsystem`, `RepairSubsystem`,
  `SensorSubsystem`, `ShieldClass`, plus their `*Property` data
  classes.
- **Multiplayer** — `MultiplayerGame`, `MultiplayerWindow`,
  `MultiplayerInterfaceHandlers`, `InitNetwork`, `NetFile`, `Network`,
  `Message`, `SkipChecksum`, `SystemChecksumFail`, `ServerListEvent`,
  `SortServerListEvent`.
- **Mission/set** — `Mission`, `MissionLib`, `SetClass`,
  `SetInstance`, `SetManager`, `BridgeSet`, `System`, `Game`,
  `GameInit`, `GameSpy`.
- **Space objects** — `Planet`, `Nebula`, `MetaNebula`, `Sun`,
  `Asteroid`, `AsteroidField`, `AsteroidTile`, `Backdrop`,
  `BackdropSphere`, `StarSphere`, `Waypoint`.
- **AI** — `ArtificialIntelligence`, `BuilderAI`, `ConditionalAI`,
  `PlainAI`, `PreprocessingAI`, `RandomAI`, `SequenceAI`,
  `PriorityListAI`.
- **Bridge / characters** — `Captain`, `CharacterClass`,
  `BridgeObjectClass`, `CharacterAction`,
  `CharacterSpeakingQueue`.

---

## UI hierarchy

The UI class tree:

```
TGEventHandlerObject
  └── TGUIObject              # bounds, visibility, parent link
       └── TGPane              # child container, linked-list children
            ├── TGScrollablePane
            │    └── TGTextBlock         # console/chat (also called TGConsole)
            ├── TGWindow
            ├── STWidget
            │    └── STButton
            │         └── STToggle
            ├── TGIcon
            ├── TGParagraph
            └── TGRootPane     # cursor/tooltip/focus
```

`TGTextBlock` is exposed as `TGConsole` in the SWIG bindings.

### `TGUIObject` layout

| Offset | Type    | Field      | Notes                                |
|--------|---------|------------|--------------------------------------|
| `+0x14`| ptr     | `parent`   | Parent `TGPane*`                     |
| `+0x18`| Rect    | `bounds`   | `{x, y, w, h}` parent-relative       |
| `+0x28`| uint32  | `flags`    | See bit table below                  |
| `+0x2C`| ptr     | `callbacks`| Event-callback data                  |

Flag bits at `+0x28`:

| Bit         | Meaning                                                |
|-------------|--------------------------------------------------------|
| `0x00000008`| Visible                                                |
| `0x00000020`| Skip parent in rendering chain                         |
| `0x00000040`| Exclusive keyboard focus                               |
| `0x00000080`| Dirty (needs repaint)                                  |
| `0x00000100`| Hidden                                                 |
| `0x00000200`| Disabled                                               |
| `0x10000000`| Layout in progress (`TGParagraph` recalc guard)        |

### MainWindow children of `TopWindow`

`TopWindow` (the root game window at `0x0097E238`) creates these
children, identifiable by integer type ID in their `+0x4C` field:

| ID | Class                  | Description                          |
|----|------------------------|--------------------------------------|
| 0  | `BridgeWindow`         | 3D bridge crew view                  |
| 1  | `TacticalWindow`       | 3D tactical combat view              |
| 2  | `ConsoleWindow`        | Debug console (half-height overlay)  |
| 5  | `PlayWindow`           | Mission play viewport                |
| 7  | `SortedRegionMenuWindow`| Star map / system selection         |
| 8  | `MultiplayerWindow`    | Multiplayer lobby                    |
| 9  | `PlayViewWindow`       | Play viewport overlay                |
| 10 | `CinematicWindow`      | Cutscene overlay                     |

`TopWindow` constructor (`0x0050C430`) creates exactly five children
in this order: `MainWindow` (varies by mode), `ConsoleWindow` (2),
`MultiplayerWindow` (8), `PlayWindow` (5), `CinematicWindow` (10).
`TopWindow::FindMainWindow` (`0x0050E1B0`) iterates children matching
RTTI type `0x810F` and the type ID at `+0x4C`.

### `PlayWindow` is the `Game` object

There are two distinct classes that early disassembly mistakes for
each other:

| Class             | Constructor   | Base                              | Role                                                       |
|-------------------|---------------|------------------------------------|------------------------------------------------------------|
| `PlayWindow`      | `0x00405C10`  | `MissionBase` (`TGEventHandlerObject`) | The "Game" object — game state, scoring, episodes; this is the SWIG `Game` |
| `PlayViewWindow`  | `0x004FC480`  | `MainWindow` (`TGScrollablePane`)  | UI rendering viewport, type ID 9                          |

`PlayWindow` (the Game object) layout:

| Offset | Type    | Field           |
|--------|---------|-----------------|
| `+0x38`| int     | `score`          |
| `+0x3C`| int     | `rating`         |
| `+0x40`| int     | `kills`          |
| `+0x54`| `Ship*` | `playerShip`     |
| `+0x60`| bool    | `godMode`        |
| `+0x6C`| int     | `terminateEvent` |
| `+0x70`| `Episode*`| `currentEpisode` |

Inherited from `MissionBase`:

| Offset | Field         |
|--------|---------------|
| `+0x14`| `moduleName` (Python module path) |
| `+0x1C`| type ID       |

`MultiplayerGame` extends `PlayWindow`:

| Offset | Field                |
|--------|----------------------|
| `+0x74`| `playerSlots[16]`    |
| `+0x1F8`| `readyForNewPlayers`|
| `+0x1FC`| `maxPlayers`        |

### `TGDialogWindow` button bitfield

`TGDialogWindow::AddButtons` accepts a bitfield:

| Bit       | Button      |
|-----------|-------------|
| `0x000001`| OK          |
| `0x000002`| Cancel      |
| `0x000004`| Yes         |
| `0x000008`| No          |
| `0x000010`| Abort       |
| `0x000020`| Retry       |
| `0x000040`| Continue    |
| `0x000080`| Ignore      |
| `0x200000`| Read-only mode (no buttons) |

### TGL resource files

The UI is largely resource-driven. The two important TGL files:

| File                         | Contents                                       |
|------------------------------|------------------------------------------------|
| `data/TGL/Multiplayer.tgl`   | MP lobby buttons, mission list, player list    |
| `data/TGL/Options.TGL`       | Quit dialog, graphics/sound settings           |

### RTTI type IDs (from `TGEventHandlerObject` slot 1)

| ID      | Class                                   |
|---------|-----------------------------------------|
| `0x810F`| `MainWindow` (base for full-screen views)|
| `0x205` | `TGConsole` / `TGTextBlock`             |
| `0x80EA`| `STRadioGroup`                          |

---

## Function map (broad strokes)

The binary contains 18,247 functions in total: 13,333 `FUN_*`
addresses, 133 thunks, 86 named imports / CRT, 4,692 SEH unwind
handlers, and 3 catch handlers. Address range
`0x004010E0`–`0x008879E0`.

A coarse partition by address range. Useful for orienting a Ghidra
session: when you land in an unfamiliar `FUN_*`, the address tells you
which subsystem you're in.

| #  | Range                 | Subsystem                                         | Count   |
|----|-----------------------|---------------------------------------------------|---------|
| 1  | `0x0040`–`0x0042`     | Core / base objects (TGObject, TGString, mem mgmt)| 646     |
| 2  | `0x0043`–`0x0045`     | UtopiaApp / UtopiaModule / init                   | 717     |
| 3  | `0x0046`–`0x004B`     | UI framework / widget library                     | 1,241   |
| 4  | `0x004C`–`0x0051`     | Windows / dialogs / screens                       | 1,112   |
| 5  | `0x0052`–`0x005A`     | Game logic / ships / AI / tactical                | 2,073   |
| 6  | `0x005B`–`0x0065`     | Sparse: mission system, large objects             | 201     |
| 7  | `0x0066`–`0x0068`     | Scene graph / 3D objects                          | 527     |
| 8  | `0x0069`–`0x0069D`    | Game session / pre-multiplayer                    | 159     |
| 9  | `0x0069E`–`0x006A2`   | **MultiplayerGame**                               | 44      |
| 10 | `0x006A3`–`0x006A7`   | **NetFile / checksum manager**                    | 58      |
| 11 | `0x006A8`–`0x006AF`   | Hash tables / containers                          | 141     |
| 12 | `0x006B0`–`0x006BF`   | **TGNetwork / TGWinsockNetwork**                  | 225     |
| 13 | `0x006C0`–`0x006CF`   | Streams / serialization                            | 246     |
| 14 | `0x006D0`–`0x006DF`   | **Events / timers / TGEventManager**              | 327     |
| 15 | `0x006E0`–`0x006EF`   | Config / VarManager / misc                        | 226     |
| 16 | `0x006F0`–`0x006FF`   | GameSpy / SWIG bindings                           | 273     |
| 17 | `0x0070`–`0x0076`     | Python 1.5 / SWIG method tables                   | 1,619   |
| 18 | `0x0077`–`0x0084`     | NetImmerse 3.1 / D3D7 renderer                    | 2,915   |
| 19 | `0x0085`–`0x0086`     | CRT / stdlib / Winsock IAT                         | 787     |
| 20 | `0x0087`–`0x0088`     | Exception handling / unwind tables                | 4,710   |

### Notable named entry points

Initialisation:
- `0x00445D90` — `UtopiaModule::InitMultiplayer` (creates WSN +
  NetFile + GameSpy)
- `0x006B3EC0` — `TGNetwork::HostOrJoin` (socket + state)
- `0x006A30C0` — `NetFile` constructor (creates 3 hash tables —
  capacities A/B/C all `0x25` — and registers handler on event
  `0x60001`)

Per-frame:
- `0x0043B4F0` — `UtopiaApp::MainTick`
- `0x006B4560` — `TGNetwork::Update`
- `0x006DA2C0` — `TGEventManager::ProcessEvents`
- `0x00451AC0` — Simulation pipeline tick (calls `TGNetwork::Update`)

UI / startup:
- `0x005046B0` — Register MultiplayerWindow handlers
- `0x00504890` — Start-game button click
- `0x00504F10` — Setup MultiplayerGame (from opcode 0x01)

MultiplayerGame handlers (the addresses listed against the event-handler
table in `architecture/runtime-and-main-loop.md`):
- `0x0069E590` constructor, `0x0069EBB0` destructor,
  `0x0069EFE0` register-all-handlers, `0x0069F2A0` ReceiveMessage,
  `0x006A0A30` NewPlayer, `0x006A1B10` ChecksumComplete,
  `0x006A1E70` NewPlayerInGame.

NetFile / checksum opcode handlers:
- `0x006A3CD0` `NetFile::ReceiveMessageHandler` (opcode dispatcher
  `0x20`–`0x27`)
- `0x006A3820` ChecksumRequestSender — queues 4 requests, sends #0
- `0x006A39B0` ChecksumRequestBuilder
- `0x006A4260` Server: ChecksumResponseEntry → `0x006A4560` verifier
- `0x006A4A00` ChecksumFail — fires `0x8000E7`, sends `0x22`/`0x23`
- `0x006A4BB0` All passed — fires `0x8000E8`
- `0x006A5DF0` Client: ChecksumRequestHandler
- `0x006A5860` File transfer processor
- `0x0071F270` ComputeChecksum + `0x007202E0` HashString

TGNetwork pump:
- `0x006B5080` Queue message to peer (used by `TGNetwork::Send`)
- `0x006B55B0` SendOutgoingPackets
- `0x006B5C90` ProcessIncomingPackets (recvfrom loop)
- `0x006B5F70` DispatchIncomingQueue
- `0x006B61E0` Reliable ACK handler (priority queue at `peer+0x9C`)
- `0x006B6AD0` DispatchToApplication
- `0x006B9B20` CreateUDPSocket (bind + non-blocking)
- `0x006B9BB0` Set port (writes to `WSN+0x338`)

Event manager:
- `0x006DA130` Register named handler function
- `0x006DA2C0` `EventManager::ProcessEvents`
- `0x006DA300` Dispatch single event
- `0x006DB380` Register event handler (binds handler to event type)
- `0x006DB620` Dispatch to handler chain

### Important `TGWinsockNetwork` field offsets

| Offset       | Field                                              |
|--------------|----------------------------------------------------|
| `WSN+0x10C`  | Send-enabled flag (checked by SendOutgoingPackets) |
| `WSN+0x10E`  | `IsHost` flag (1=host, 0=client)                   |
| `WSN+0x10F`  | Join-in-progress flag                              |
| `WSN+0x194`  | UDP socket handle (shared with GameSpy)            |
| `WSN+0x338`  | Port number                                        |
| `WSN+0x2C` / `WSN+0x30` | Peer-array pointer + count               |
| `WSN+0xF4` / `WSN+0xF8` / `WSN+0xFC` | Group array ptr / count / cap |

### `NetFile` opcode dispatcher

`NetFile::ReceiveMessageHandler` (`0x006A3CD0`) is registered on event
`0x60001` and dispatches by first message byte:

| Opcode | Handler        | Role                                               |
|--------|----------------|----------------------------------------------------|
| `0x20` | `FUN_006A5DF0` | Client: checksum request                           |
| `0x21` | `FUN_006A4260` | Server: checksum response (→ `0x006A4560` verifier)|
| `0x22` | `FUN_006A4C10` | Checksum fail (file mismatch)                      |
| `0x23` | `FUN_006A4C10` | Checksum fail (reference mismatch)                 |
| `0x25` | (inline)       | File transfer (with one-time "Receive File Warning" dialog) |
| `0x27` | `FUN_006A4250` | (purpose unknown)                                  |

The 4 initial checksum requests built by ChecksumRequestSender:

```
0  scripts/App.pyc
1  scripts/Autoexec.pyc
2  scripts/ships/*.pyc
3  scripts/mainmenu/*.pyc
```

Wire format of one checksum request, opcode `0x20`:

```
byte   0x20
byte   index           (0..3)
ushort dir_len
bytes  dir
ushort filter_len
bytes  filter
byte   recursive
```

The server queues all 4 in NetFile hash table `B` and sends index 0
immediately. Subsequent indices send only after the previous response
verifies (`FUN_006A5290` success path).

A subtle quirk worth knowing: the client checksum handler
(`FUN_006A5DF0`) silently does **not** send a response if no files
match the directory/filter combination — there's no negative response
opcode, so the server side simply sees nothing.

---

## Engine globals (cross-reference)

For convenience, the same global memory addresses summarised in
`architecture/runtime-and-main-loop.md`:

```
0x0097E238  TopWindow / Game object pointer (also MultiplayerGame)
0x0097F810  TGTimerManager #2 (wall-clock timers)
0x0097F838  TGEventManager
0x0097F864  Handler registry (EventManager+0x2C)
0x0097F898  TGTimerManager #1 (game-time timers)
0x0097FA00  UtopiaModule base
0x0097FA78  TGWinsockNetwork pointer (UtopiaModule+0x78)
0x0097FA7C  GameSpy pointer (UtopiaModule+0x7C; +0xDC = qr_t)
0x0097FA80  NetFile / ChecksumMgr (UtopiaModule+0x80)
0x0097FA88  IsClient (BYTE)
0x0097FA89  IsHost (BYTE)
0x0097FA8A  IsMultiplayer (BYTE)
0x0097E9C8  Set-list pointer
0x0099EE38  Python nesting counter (must be 0 for PyRun_String)
0x009A09D0  Clock object pointer (+0x90 = gameTime, +0x54 = frameTime)
0x009A1468  NiObject NiRTTI data
0x009A2B98  NiRTTI factory hash table pointer
```
