# Deferred: phaser hardpoint methods we aren't calling

**Status:** deferred 2026-05-18.  PR `feat/phaser-prism-taper-scroll`
ships the renderer-side fidelity work (prism geometry, four-channel
colours, taper family, perimeter tile, texture scroll, length tiles,
SDK texture path, range-clip on the visible beam).  A scan of all
`DorsalPhaser1.Set*(…)` calls in `sdk/Build/scripts/ships/Hardpoints/galaxy.py`
turns up another batch of properties the BC engine consumes that we
don't yet model.

This file is the punch-list for the next phaser-hardpoint pass.  None
of these block combat from working at the level we ship today — they
control HUD presentation, AI/group routing, damage-radius behaviour,
and edge-case firing modes.

## What we already wire up

Pulled through `PhaserProperty` (engine/appc/properties.py) and
mirrored on `ShipSubsystem` (engine/appc/subsystems.py):

- Geometry: `PhaserWidth`, `MainRadius`, `CoreScale`, `NumSides`,
  `TaperRadius`, `TaperRatio`, `TaperMinLength`, `TaperMaxLength`
- Texture: `TextureName`, `LengthTextureTilePerUnit`, `PerimeterTile`,
  `TextureSpeed`
- Colours: `OuterShellColor`, `InnerShellColor`, `OuterCoreColor`,
  `InnerCoreColor`
- Combat: `MaxDamage`, `MaxDamageDistance`, `MaxCharge`,
  `MinFiringCharge`, `NormalDischargeRate`, `RechargeRate`,
  `ArcWidthAngles`, `ArcHeightAngles`, `FireSound`, `Position`,
  `Orientation`, `Length`

## What we don't wire up yet

Each entry is `SDK method` — `purpose (where I think it lands)` —
`why deferred`.

### Visual / animation polish

- `SetPhaserTextureStart` / `SetPhaserTextureEnd` —
  Range of texture rows the bank uses, picked per discharge (BC cycles
  through animation frames inside the strip). Without this we use the
  whole strip with continuous scroll, which is close enough but loses
  the discrete "frame index per shot" feel.
  Defer: needs a per-shot animation counter + a way to expose the row
  range to the shader; the current scroll already gives motion.
- `SetWidth` —
  Distinct from `PhaserWidth`; on galaxy.py the value is the same as
  PhaserWidth, so we currently ignore it. Plausible it's a runtime
  override (e.g. damaged banks taper visually) or an unused legacy.
  Defer: needs grepping for any *runtime* setter calls in SDK before
  guessing semantics.

### HUD / icons

- `SetIconNum` — Bank icon slot in the weapons HUD.
- `SetIconPositionX` / `SetIconPositionY` — Icon screen position.
- `SetIconAboveShip` — Whether the bank's marker draws above its 3D
  position (over-the-ship indicator vs in the panel).
- `SetIndicatorIconNum` —  Range/arc indicator icon slot.
- `SetIndicatorIconPositionX` / `SetIndicatorIconPositionY` —
  Indicator screen position.

  Defer as a group: we don't yet have a phaser-bank HUD panel — the
  target list shows ship-level systems only.  When we build the
  weapons panel, these become its layout source.

### Damage shape

- `SetDamageRadiusFactor` —
  Splash-radius factor for the hit (so a beam that lands near a shield
  edge still tickles adjacent facets).  Today we apply damage to the
  exact target only.
- `SetRadius` —
  Probably the bank's "physical" damageable hit-volume, not the beam
  radius.  Used when targeting a *bank* (vs a system) for hardpoint
  damage.

  Defer: requires deciding whether the target-list ever exposes
  individual banks, and how splash maps onto our shield-facet model.

### Firing-mode flags

- `SetDumbfire` —
  Bank ignores lock and fires straight along its orientation.  Off
  for primary phasers; relevant for certain torpedoes and AI
  cone-fire patterns.
  Defer: implies a non-target-locked fire path; ours only fires at a
  locked target.
- `SetPrimary` —
  Marks the bank as part of the primary-weapon group (vs secondary
  torpedoes etc).  Today PhaserSystem assumes its banks are primary.
  Defer: low-priority while we only model phasers + torpedoes as
  separate systems.
- `SetTargetable` —
  Whether the *bank itself* shows up as a targetable hardpoint.  Tied
  to `SetRadius` above.
- `SetGroups` —
  Bitmask used for "fire group" routing in BC (which banks fire on
  the same trigger).  Player-side we trigger all eligible banks in
  arc together; AI uses this to coordinate volleys.
- `SetWeaponID` —
  Stable string ID used by save/load, AI, and the HUD to refer to
  this bank.  Today we key on the hardpoint name; replacing that with
  the explicit WeaponID would survive ship-class renaming.

### Repair / status

- `SetMaxCondition` — Max HP of the bank as a damageable subsystem.
  Today we treat the bank as part of the ship-level Phasers system
  HP, not as its own destroyable hardpoint.
- `SetRepairComplexity` — Time/skill cost when crew repairs this
  bank.  Engineering rotation isn't modelled yet.

## Where the fix lands when we resume

- `engine/appc/properties.py` — add typed accessors for each method
  on `PhaserProperty`, defaulting to BC's no-op semantics.
- `engine/appc/subsystems.py` — mirror onto `ShipSubsystem` so the
  hardpoint loader sees them via the same SDK SetX path it already
  uses for the colours / taper family.
- HUD work lives in `engine/ui/` and the (not-yet-existing) weapons
  panel; until that panel exists, the icon setters can stay no-ops.

## Related work

- [`docs/superpowers/specs/2026-05-14-phaser-combat-design.md`](../specs/2026-05-14-phaser-combat-design.md)
  — PR 2c spec; explicitly scopes out HUD and per-bank damageability.
- [`docs/superpowers/deferred/2026-05-18-phaser-fire-range-gate.md`](2026-05-18-phaser-fire-range-gate.md)
  — Companion deferred item for the firing-side range gate.
