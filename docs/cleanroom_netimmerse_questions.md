# NetImmerse 3.1 SDK — Clean-Room Questionnaire

## Purpose

This document is the **only artifact** that crosses from the clean side into the contaminated side. A reader with access to the NetImmerse 3.1 SDK (source, headers, docs, samples) will answer these questions in **their own prose**, then return the answers as a separate document.

The answers feed open_stbc's NIF renderer (Phase 2), animation, and audio subsystems. Today the NIF code path is OpenMW-derived, with BC-specific block types layered on per NifSkope's reverse-engineered tables. The SDK should let us *settle* interpretation ambiguities that file-format inspection alone cannot resolve.

## Clean-room protocol — rules for the reader

These rules protect the reimplementation's clean-room status. Follow them strictly.

1. **No source code paste.** Do not copy header definitions, struct layouts, function bodies, comments, or any other verbatim text from the SDK. Describe behavior in your own words.
2. **No filenames or symbol names from non-public surfaces.** Public class names that appear in the file format (e.g. `NiNode`, `NiAlphaProperty`) are fine because they appear in every NIF file already. Internal helper class names, file paths inside the SDK, and private API symbols are not.
3. **Behavior over implementation.** Answer "what does this do" not "how is it written." If two implementations would produce identical observable behavior, the implementation detail is contamination.
4. **Cite confidence.** For each answer, tag one of: **[documented]** (stated in SDK docs/headers), **[inferred from sample]** (observed in sample app behavior), **[inferred from source]** (deduced from reading implementation), **[not found]**. We need to know how load-bearing each answer is.
5. **Note absences explicitly.** "Not in this SDK" is a valid and useful answer. Don't skip a question — say it wasn't there.
6. **Versions.** If you find something specific to 3.0 vs 3.1 vs later, note it. BC shipped in 2002 against roughly this era; we care about 3.1 but adjacent versions are informative.
7. **No diagrams reproduced verbatim.** If a diagram is illustrative, describe what it shows in prose.
8. **One answer document.** Number your answers with the same IDs used here (`NI-Q##`). Return everything as one markdown document.

## How to use this list

Questions are grouped by subsystem and tagged by priority:

- **[P1]** — directly blocks Phase 2 implementation; high-confidence answer required.
- **[P2]** — would resolve known ambiguities in our current OpenMW-based interpretation.
- **[P3]** — speculative; may not be in the SDK. Skip with "[not found]" if absent.

Within each section, questions are ordered roughly from foundational to derived.

---

## A. File format and serialization

- **NI-Q1 [P1]** What does the file header look like — magic bytes, version field encoding, endianness marker? How is the version field interpreted (decimal-encoded integer? packed nibbles?)?
- **NI-Q2 [P1]** Is byte order always little-endian, or does the header encode endianness? Are there platform-specific NIF builds?
- **NI-Q3 [P1]** How is the block list laid out — count first, then blocks in order? Is block ordering meaningful (e.g. must children appear before parents, or vice versa, or is it free)?
- **NI-Q4 [P1]** How are inter-block references encoded — integer indices, pointers fixed up on load, names? Are there separate "strong" (owning) and "weak" (non-owning) reference types?
- **NI-Q5 [P2]** Can the graph contain cycles? If so, which block types legitimately introduce them?
- **NI-Q6 [P1]** Is there a global string table, or are strings inline per block, or both? How are duplicate strings handled?
- **NI-Q7 [P2]** What happens on load when a block type is unknown — fatal error, skipped, treated as opaque? Is there a "skip unknown" mechanism the BC team could have used for custom blocks?
- **NI-Q8 [P2]** Is there an explicit "footer" or trailing index — root node list, named-object index, dependency index?
- **NI-Q9 [P3]** Are there compressed NIF variants, or is the format always raw?
- **NI-Q10 [P3]** Is there any embedded checksum, signature, or DRM-style integrity check?
- **NI-Q11 [P2]** How are null references represented in serialized form, and how do they differ from "missing optional"?
- **NI-Q12 [P2]** Are float values stored as IEEE-754 single throughout, or do some fields use other formats (half, fixed-point)?
- **NI-Q13 [P3]** Is there any documented file-format extension hook — block-type registration, custom-block ID range, version-suffix conventions for vendor extensions?

## B. Scene graph semantics

- **NI-Q14 [P1]** What is the transform composition order on `NiAVObject` / `NiNode` — translation, rotation, scale: T·R·S? S·R·T? Is scale uniform only or per-axis?
- **NI-Q15 [P1]** When a parent transform changes, when do child world transforms update — eagerly on set, lazily on read, only during a scene-wide update tick?
- **NI-Q16 [P1]** What are the flag bits on `NiAVObject` and what does each one mean (hidden, selective update, app culled, render culled, etc.)? Distinguish "app culled" from "render culled" if both exist.
- **NI-Q17 [P1]** How are bounding volumes computed and propagated — does a child's bounds always inflate the parent's, and when is the recomputation triggered?
- **NI-Q18 [P2]** Are bounding volumes spheres, AABBs, OBBs, or all three? Which is authoritative for culling vs picking vs collision?
- **NI-Q19 [P1]** Walk through `NiSwitchNode` evaluation: how is the active child selected? Per-frame? On a controller? Manually?
- **NI-Q20 [P1]** Walk through `NiLODNode` / `NiRangeLODData` evaluation: how is the distance computed (camera-to-node-origin, camera-to-bounds-nearest?), and how are LOD bands defined?
- **NI-Q21 [P1]** `NiBillboardNode` modes — what axes can be locked, and is the up-vector world-up or parent-up? When does the billboard orient — pre-cull or post-cull?
- **NI-Q22 [P2]** Does `NiNode` distinguish between "scene graph child" and "render-only child" — i.e. anything that's part of the transform hierarchy but not drawn?
- **NI-Q23 [P2]** What is the canonical traversal order for scene updates: per-frame world-transform refresh, then per-frame controller tick, then cull, then render? Where does animation evaluation fit?
- **NI-Q24 [P2]** Are there "selective update" semantics — nodes that opt out of automatic transform updates and require explicit refresh?
- **NI-Q25 [P3]** Is there a "scene root" type distinct from `NiNode`, with extra responsibilities?

## C. Geometry

- **NI-Q26 [P1]** What vertex attributes are storable per `NiTriShape` / `NiTriShapeData` — positions, normals, vertex colors, UVs (how many sets?), tangents/bitangents? How is presence flagged?
- **NI-Q27 [P1]** Are normals always per-vertex, or can they be per-face? If per-vertex, are they in object space or some other space?
- **NI-Q28 [P1]** `NiTriStrips` / `NiTriStripsData` — what is the strip-restart convention (degenerate triangles, restart index, separate strip lists)? Are strip orientations consistent or does the renderer flip culling per strip?
- **NI-Q29 [P2]** How many UV sets are supported, and how does a texture stage select which set to use?
- **NI-Q30 [P2]** Vertex color: is there a documented "modulate against material" vs "replace material" mode?
- **NI-Q31 [P2]** Are tangents/bitangents ever stored, or always derived at runtime? If stored, what's the encoding (full vec3 each, or compressed)?
- **NI-Q32 [P2]** Is there a separate "skinned geometry" data type, or does skinning attach to ordinary geometry via `NiSkinInstance`?
- **NI-Q33 [P2]** Index buffer width — always 16-bit, or 32-bit when needed?
- **NI-Q34 [P3]** Any vertex-cache optimization hints in the format (e.g. pre-sorted for post-transform cache)?

## D. Materials and rendering properties

- **NI-Q35 [P1]** `NiMaterialProperty` channels — what is the exact lighting semantics of ambient, diffuse, specular, emissive, and the alpha and glossiness fields? Which channels contribute when no light is hitting the surface?
- **NI-Q36 [P1]** Is specular gated by a separate property (e.g. `NiSpecularProperty`) or by a flag on `NiMaterialProperty`, or both?
- **NI-Q37 [P1]** `NiAlphaProperty` flags layout — what bits control: alpha-blend on/off, source blend factor, dest blend factor, alpha-test on/off, alpha-test function, alpha-test reference, no-sort flag? Provide the meaning of each field, not the bit positions.
- **NI-Q38 [P1]** What is the documented draw-order policy for alpha-blended geometry — back-to-front by node-origin distance, back-to-front by bounds-nearest, or unsorted with the "no-sort" flag relevant?
- **NI-Q39 [P1]** `NiZBufferProperty` — separate bits for depth test, depth write, and depth-test function? What functions are supported?
- **NI-Q40 [P2]** `NiStencilProperty` — full semantics: enable, fail/zfail/pass actions, function, reference, mask.
- **NI-Q41 [P1]** `NiTexturingProperty` — what are the named stage slots (base, dark, detail, gloss, glow, bump map, decal 0-N)? For each slot, what's the documented use and combiner formula against the previous stage?
- **NI-Q42 [P1]** For each texture stage, what is the documented filter mode set (nearest, bilinear, trilinear, anisotropic) and clamp mode set (clamp, wrap, mirror, clamp-to-edge)?
- **NI-Q43 [P2]** Is there a "glow stage" combiner that uses a glow texture additively in a documented way, independent of emissive material color?
- **NI-Q44 [P2]** `NiSourceTexture` — how is the pixel format described (palette, internal format enum, external file reference)? Are mipmaps always generated, sometimes stored, or a per-texture flag?
- **NI-Q45 [P2]** Texture transform controllers — how are translate/rotate/scale on UVs composed, and which UV-set does the transform apply to?
- **NI-Q46 [P2]** Is there environment / cube-map support documented at the property level, or is that a BC-era extension?
- **NI-Q47 [P2]** `NiVertexColorProperty` — what are the documented "source vertex mode" and "lighting mode" options, and how do they interact with `NiMaterialProperty`?
- **NI-Q48 [P2]** `NiShadeProperty` — flat / Gouraud / Phong / etc.: which shading models are documented?
- **NI-Q49 [P2]** `NiDitherProperty`, `NiWireframeProperty` — semantics if present.
- **NI-Q50 [P2]** `NiFogProperty` — fog model (linear, exp, exp²), vertex vs pixel, blend with background.
- **NI-Q51 [P2]** What is the documented property-stack resolution rule when both a `NiNode` ancestor and a `NiTriShape` carry the same property type — does the closer wins, or do they combine?
- **NI-Q52 [P3]** Is there a documented multi-pass mechanism for legacy hardware fallback, and how does the format describe passes?

## E. Lighting

- **NI-Q53 [P1]** `NiAmbientLight`, `NiDirectionalLight`, `NiPointLight`, `NiSpotLight` — for each, the documented parameter set: color (split into ambient/diffuse/specular?), attenuation coefficients, cone angles.
- **NI-Q54 [P1]** Lights attach to the scene graph as `NiNode` children — do they inherit transform? Does a directional light's direction come from the node's forward axis, and which axis is "forward"?
- **NI-Q55 [P1]** Attenuation math for point and spot lights — constant/linear/quadratic falloff, or a documented curve?
- **NI-Q56 [P2]** Is there a hard limit on simultaneous lights, or is it driver-dependent? Is there a documented light-selection algorithm when too many are in range?
- **NI-Q57 [P2]** Does the specular contribution use the light's specular color or the diffuse color? Is there a per-material specular-ignore flag?
- **NI-Q58 [P3]** Any documented support for projected light textures, light cookies, or shadow primitives in this SDK era?

## F. Animation

- **NI-Q59 [P1]** Controller architecture overview: how does a `NiTimeController` chain attach to a target, and how is `target` resolved — by pointer at load, by name lookup, or both?
- **NI-Q60 [P1]** Per-controller fields: start time, stop time, frequency, phase, cycle type (loop/reverse/clamp). What does each mean exactly, and are start/stop inclusive?
- **NI-Q61 [P1]** When the current time is outside [start, stop], what does each cycle type do — clamp to nearest, wrap, ping-pong?
- **NI-Q62 [P1]** Rotation key types supported in `NiKeyframeData` — LINEAR, BEZIER (TBC), TCB, XYZ_ROTATION_KEY. Describe the math for each: what fields are stored, how interpolation is computed.
- **NI-Q63 [P1]** Quaternion interpolation — is it slerp, normalized lerp (nlerp), squad? Does the implementation pick the shorter arc, and how is the "dot product negative ⇒ negate one quat" rule handled?
- **NI-Q64 [P1]** XYZ_ROTATION_KEY — three independent scalar channels for X, Y, Z rotation: in what order are they composed into a rotation (XYZ Euler? extrinsic? intrinsic?), and what are the units (radians vs degrees)?
- **NI-Q65 [P1]** TCB (tension/continuity/bias) interpolation — what is the documented formula, and how do tangents at boundary keys behave?
- **NI-Q66 [P1]** Bezier rotation keys — how are tangents encoded (in-tangent + out-tangent? handle points?), and in what space?
- **NI-Q67 [P1]** Position and scale key interpolation — same key types and formulae as rotation, or different?
- **NI-Q68 [P1]** `NiKeyframeController` vs `NiTransformController` — what's the difference, and which is preferred in 3.1?
- **NI-Q69 [P1]** `NiControllerSequence` — what does it represent, and how does it differ from a raw controller chain? How are target nodes resolved within a sequence (by name in the scene graph?)?
- **NI-Q70 [P1]** `NiControllerManager` — activation, deactivation, blending between sequences. What's the documented blend model — additive, override, weighted average?
- **NI-Q71 [P1]** `NiBlendInterpolator` — how do multiple sources contribute, how are weights summed, what happens when weights don't sum to 1?
- **NI-Q72 [P2]** How are controller chains updated when multiple controllers target the same property on the same object? Priority? Insertion order? Last-writer-wins?
- **NI-Q73 [P2]** What time delta is passed to a controller — frame-clamped, real-time, scaled? Is there a documented max-step?
- **NI-Q74 [P2]** `NiTextKeyExtraData` — what's the canonical interpretation of text-key tags (e.g. "start", "end", "soundN", "loopN")? Are tag strings standardized in this SDK, or fully application-defined?
- **NI-Q75 [P2]** `NiUVController` — exact parameters and interpolation.
- **NI-Q76 [P2]** `NiVisController` — boolean visibility track encoding.
- **NI-Q77 [P2]** `NiColorController`, `NiAlphaController`, `NiMaterialColorController` — channel selection and target mapping.
- **NI-Q78 [P2]** `NiMorphData` and `NiGeomMorpherController` — vertex morph blending formula, base shape vs target shapes, weight normalization.
- **NI-Q79 [P2]** `NiPathController` — path representation, banking, follow rules.
- **NI-Q80 [P2]** `NiLookAtController` — target resolution, axis lock, up-vector source.
- **NI-Q81 [P2]** Are animation curves resampled at load to a fixed rate, or evaluated at original key density at runtime?
- **NI-Q82 [P3]** Is there documented IK support in 3.1, or is that later?

## G. Skinning

- **NI-Q83 [P1]** `NiSkinInstance` — what fields exist (bone list, skeleton root reference, skin data, optional skin partition)? What's the role of each?
- **NI-Q84 [P1]** `NiSkinData` — bone bind matrices: are they bind-pose bone-to-skin or skin-to-bone? Documented sign and axis conventions.
- **NI-Q85 [P1]** `NiSkinData` vertex weights — how many influences per vertex maximum? How is the weight list terminated (count field, sentinel)?
- **NI-Q86 [P1]** Weight normalization — are weights expected to sum to 1, or does the runtime renormalize? What happens if they don't?
- **NI-Q87 [P1]** Bind-pose space — are bind matrices in skeleton-root space, parent-bone space, or world space at bind time?
- **NI-Q88 [P1]** Skinning math at runtime — linear blend skinning formula and the exact matrix chain used (mesh-local → bind-inverse → bone-current → ...?).
- **NI-Q89 [P2]** `NiSkinPartition` — what does partitioning optimize for (per-draw bone palette limit)? How are strips/triangles allocated to partitions?
- **NI-Q90 [P2]** Maximum bones per partition / per draw call — fixed in 3.1, or hardware-dependent?
- **NI-Q91 [P2]** Normals under skinning — are they re-skinned with the inverse-transpose, or with the regular matrix, or pre-baked?
- **NI-Q92 [P3]** Dual-quaternion skinning support — present in 3.1 or later only?

## H. Particles and effects

- **NI-Q93 [P2]** `NiParticleSystem` / `NiParticles` — overall data model: emitter, modifiers (force, age, collision), renderer.
- **NI-Q94 [P2]** Emitter shapes supported (point, box, sphere, cylinder, mesh)? Per-emitter parameters?
- **NI-Q95 [P2]** Per-particle state — position, velocity, age, lifetime, color, size, rotation? What's tracked and how?
- **NI-Q96 [P2]** Particle aging / death — how is "expired" determined, and when are slots reused?
- **NI-Q97 [P2]** Force modifiers — gravity, drag, wind, vortex: which are built-in?
- **NI-Q98 [P2]** Collision modifier — does it support arbitrary mesh collision, or just planes/spheres?
- **NI-Q99 [P2]** Particle rendering — billboards always camera-facing, or other modes (axis-locked, mesh particles)?
- **NI-Q100 [P3]** Is there a documented trail / ribbon primitive in 3.1?
- **NI-Q101 [P3]** Is there a `NiLensFlare` or `NiCorona` block class? If so, parameter set and update rules.

## I. Collision (pre-Havok era)

- **NI-Q102 [P2]** What collision support exists natively in NetImmerse 3.1, before Havok integration? Block class names and data models.
- **NI-Q103 [P2]** Primitive shapes supported (sphere, box, capsule, cylinder, OBB, AABB)?
- **NI-Q104 [P2]** Mesh collision — full triangle mesh, BVH-accelerated, or per-triangle scan?
- **NI-Q105 [P2]** Collision queries supported — ray, sphere-sweep, contact pair test?
- **NI-Q106 [P3]** Is there a "trigger / sensor" concept distinct from solid collision?
- **NI-Q107 [P3]** Continuous collision detection in this era?

## J. Math and coordinate conventions

- **NI-Q108 [P1]** Handedness — is the coordinate system left-handed or right-handed?
- **NI-Q109 [P1]** Up axis — Y-up or Z-up by convention?
- **NI-Q110 [P1]** Forward axis — +X, +Y, +Z, or -Z? In particular, which axis does a `NiCamera` look down?
- **NI-Q111 [P1]** Matrix storage — row-major or column-major in memory? Are matrices applied as row-vector·matrix or matrix·column-vector in the documented math?
- **NI-Q112 [P1]** Quaternion component order in storage and in code (w-x-y-z, or x-y-z-w)?
- **NI-Q113 [P1]** Quaternion-to-matrix conversion — handedness and sign convention.
- **NI-Q114 [P2]** Euler angle convention — order (XYZ extrinsic, YXZ intrinsic, etc.) and units (radians/degrees).
- **NI-Q115 [P2]** Default units — are positions in meters, centimeters, generic units? Is there a documented "1 unit = X" rule, or is it application-defined?
- **NI-Q116 [P2]** `NiCamera` projection — how are the frustum parameters specified (FOV+aspect, or l/r/t/b)? Near/far plane convention.
- **NI-Q117 [P2]** Is there a documented "pivot point" or "center of geometry" stored anywhere on `NiAVObject` distinct from the node origin? (Relevant to a known BC issue where ship NIF origins don't match AABB centers.)
- **NI-Q118 [P3]** Are there documented helpers for swept volumes, ellipsoid casts, or other advanced math operations?

## K. Resource management and lifetime

- **NI-Q119 [P2]** Reference counting — what's the documented ownership model for cross-block references? Smart-pointer wrapper, manual addref/release, parent owns children only?
- **NI-Q120 [P2]** Texture sharing — does the runtime de-duplicate textures with the same source filename? Per scene, or globally?
- **NI-Q121 [P2]** Mesh sharing / instancing — is there a documented instancing mechanism, or are duplicate `NiTriShapeData` blocks just duplicated in memory?
- **NI-Q122 [P2]** Cleanup ordering — what's the documented destruction order for a scene (root first, leaves first, refcount-driven)?
- **NI-Q123 [P3]** Is there a memory-allocator hook / custom allocator interface in 3.1?
- **NI-Q124 [P3]** Asynchronous / streaming load — supported or not?

## L. Runtime pipeline

- **NI-Q125 [P1]** Documented render-loop order: update transforms → tick controllers → cull → sort → draw, or some other sequence? Where do "pre-render" callbacks fit?
- **NI-Q126 [P1]** Culling — frustum culling against bounding sphere, AABB, or OBB? Hierarchical (cull a parent ⇒ skip all children) or flat?
- **NI-Q127 [P2]** Is there documented occlusion culling, portal culling, or PVS support in 3.1?
- **NI-Q128 [P2]** Sort order: opaque front-to-back by depth, transparent back-to-front by depth — confirmed? Is sort key constructed from material state + depth, or pure depth?
- **NI-Q129 [P2]** State-change minimization — does the renderer sort by material/texture/shader within an opaque batch, and is that documented?
- **NI-Q130 [P3]** Multi-viewport / split-screen support documented?

## M. Extension surface (relevant to BC's custom blocks)

- **NI-Q131 [P1]** Is there a documented mechanism for registering custom block classes — a factory registry, version-number range reserved for vendor blocks, an `RTTI`-style identifier scheme?
- **NI-Q132 [P1]** Custom properties — can applications subclass `NiProperty` and have their property type participate in the standard render pipeline? What hooks must they implement?
- **NI-Q133 [P1]** Custom controllers — same question for `NiTimeController` subclasses.
- **NI-Q134 [P2]** `NiExtraData` family — is this the canonical extension hook for attaching app-specific data to nodes? What subclasses are stock vs application-defined?
- **NI-Q135 [P2]** Plugin / DLL loading — does the SDK support runtime-loaded modules that register new block types, or is everything static-linked?
- **NI-Q136 [P3]** Is there a "search-string LOD attach" or runtime texture-rebinding API that BC could have used to wire up `_glow` textures via filename substring matching after load? (BC's glow maps attach via `AddLOD` at runtime, not via NIF, per our reverse-engineering — looking for the SDK API that enables that pattern.)
- **NI-Q137 [P3]** Is there a runtime API for swapping a node's draw geometry while preserving its transform and skinning binding?

## N. Audio (long-shot — may not be in this SDK)

- **NI-Q138 [P3]** Does NetImmerse 3.1 include any audio-related block types or runtime audio APIs (`NiAudio`, `NiSourceAudio`, `NiAVSource`)?
- **NI-Q139 [P3]** If so: data model — file reference, format hints, looping, 3D-positional parameters?
- **NI-Q140 [P3]** Trigger via `NiTextKeyExtraData` "sound" tags — documented integration, or expected to be wired up by the application?

## O. Tools, samples, and test data

- **NI-Q141 [P1]** What is the canonical "load a NIF and render it" sample app shipped with the SDK? Describe its top-level loop in prose — the steps and their order — without quoting code. This is the highest-value single answer for settling pipeline questions.
- **NI-Q142 [P2]** Sample apps for animation, skinning, particles — list them and describe what each one minimally demonstrates.
- **NI-Q143 [P2]** Is there a conformance / regression suite with reference NIFs and expected output? If so, characterize what scenarios it covers.
- **NI-Q144 [P2]** Tools shipped with the SDK — Max/Maya exporters, NIF viewers, command-line converters? What are their documented capabilities and limitations?
- **NI-Q145 [P3]** Any documented "best NIF for debugging" — minimal scenes that exercise each subsystem?

## P. Documentation structure

- **NI-Q146 [P2]** Provide a one-paragraph map of the SDK documentation — what's in the "Programmer's Guide" vs "API Reference" vs "Tutorials" vs release notes, at the section level. Helps us know what other questions to ask in a follow-up.
- **NI-Q147 [P2]** Are there architectural diagrams that summarize the runtime — describe what they show (subsystem boxes and arrows) without reproducing them.
- **NI-Q148 [P2]** Are there documented "gotchas" / FAQ entries about non-obvious behavior — list the topics covered, even briefly.
- **NI-Q149 [P3]** Are there migration / changelog notes between 3.0 and 3.1 (or 3.1 and 4.0) that reveal which behaviors changed? Relevant because BC may have shipped against a specific point release.

## Q. BC-specific cross-references (long-shots informed by our reverse-engineering)

These are very targeted — we've reverse-engineered Bridge Commander far enough to suspect specific SDK mechanisms exist, and we want either confirmation or "not found."

- **NI-Q150 [P3]** **AddLOD / glow attachment.** BC uses a Python-callable `AddLOD("..._glow", ...)` to attach glow textures at runtime by filename substring match. Does the SDK have a documented API on `NiNode`, `NiLODNode`, or a global manager that adds an alternate LOD level after load by texture-name pattern? What is its documented purpose (LOD swap, alt-texture, debug overlay)?
- **NI-Q151 [P3]** **Corona / lens flare.** BC renders the sun as a procedural sphere plus an additive "corona" shell, plus a lens-flare overlay. Does the SDK contain block classes or runtime helpers named `NiCorona`, `NiLensFlare`, or `NiSunCorona` — and if so, parameter set?
- **NI-Q152 [P3]** **Center-of-geometry vs origin.** Our BC ships rotate around the NIF origin, which is not the visual centroid. Is there a documented "center of geometry" or "pivot offset" field on `NiAVObject` or a derived type, or is the expectation that the application stores this externally?
- **NI-Q153 [P3]** **Engine-wash / impulse trails.** Is there a documented "stretched billboard" or "speed-elongated particle" mode that would correspond to BC's ship engine trails?
- **NI-Q154 [P3]** **Distance-attenuated emissive.** Does the material system have a documented "emissive-only at distance" or "self-illumination distance" knob, relevant to BC's running lights?
- **NI-Q155 [P3]** **Damage decals.** Does the SDK have a documented decal-projection API that BC could have used for hit decals on hulls, or is that expected to be application-built on top of `NiTriShape`?

## R. Engineering hygiene observations (low-stakes context)

These are useful but not load-bearing. Answer briefly if at all.

- **NI-Q156 [P3]** What threading model does the runtime assume — single-threaded, render-thread-only-touches-scene-graph, fully thread-safe? Briefly.
- **NI-Q157 [P3]** What logging / diagnostics hooks exist?
- **NI-Q158 [P3]** What error-handling style does the API use — return codes, exceptions, asserts?
- **NI-Q159 [P3]** Is there a documented "validate this NIF" / "dump this scene" diagnostic API?

---

## Answer return format

When you return answers, please:

1. **Match the IDs.** `NI-Q42 [documented] <prose answer>`. One block per question.
2. **Group by section.** Same A–R sections as above.
3. **Add a top-of-document "headline findings"** — 5-10 bullets of the most surprising or load-bearing facts, so we know where to look first.
4. **Add a "not found" list at the end** — every question you couldn't answer, by ID, so we can see the negative-space coverage.
5. **No code, no struct layouts, no filenames inside the SDK tree.** Public NIF class names (those that appear in any NIF file) are fine.

If a question is ambiguous, **answer the version you think we meant and flag the ambiguity** — don't skip it asking for clarification, since you only get one round.

Thank you. This is the only artifact crossing the threshold; everything we build downstream depends on the care you take here.
