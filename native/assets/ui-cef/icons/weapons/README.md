# Hand-authored weapon icons

Drop a `{num}.svg` here to override the runtime potrace trace for that
icon number. The WeaponsDisplay panel checks this directory first; if
no file exists, it falls back to the auto-traced cache under
`cache/icons/weapons/{num}.svg`.

## Conventions

- **Filename**: `{num}.svg` where `num` matches an entry in
  `engine/ui/weapon_icons.py:ICON_REGISTRY` (e.g. `350.svg` for the
  "Top Right" phaser arc).
- **Dimensions**: set `width` / `height` in pixels to the sprite's
  native registry size (e.g. `width="54" height="24"` for icon 350).
  The panel positions icons by top-left corner; sizing the SVG
  larger than the registry entry will visually offset surrounding
  mounts.
- **Fill**: the panel CSS forces every fill inside the SVG to
  `currentColor` so the colour you draw in the editor doesn't matter
  — every path on the panel inherits from `.weapon-icon` /
  `.weapon-indicator` regardless. This is what lets theming
  (in-range glow, faction tinting, damage states) work without
  re-authoring. If you need a multi-colour icon in the future the
  override will need to relax, but for now everything renders in
  the parent's CSS colour.
- **ViewBox**: arbitrary — the browser scales the path content to
  the declared width/height.

## Registry quick-reference

| num | atlas | source x,y,w,h | description |
|---:|---|---|---|
| 330 | PhaserArcs | 0,0,54,24 | Top Left arc |
| 335 | PhaserArcs | 0,0,54,24 mirror-V | Bottom Left Curve |
| 340 | PhaserArcs | 0,28,31,54 | Bottom Left Hook |
| 350 | PhaserArcs | 0,0,54,24 mirror-H | Top Right arc |
| 355 | PhaserArcs | 0,0,54,24 rotate-180 | Bottom Right Curve |
| 360 | PhaserArcs | 0,28,31,54 mirror-H | Bottom Right Hook |
| 361 | PhaserArcs | 47,28,16,40 | Left arc |
| 362 | PhaserArcs | 47,28,16,40 mirror-H | Right arc |
| 363 | PhaserArcs | 33,87,30,10 mirror-V | Rear arc |
| 364 | PhaserArcs | 33,87,30,10 | Forward arc |
| 365 | PhaserArcs | 0,107,5,10 | Forward disruptor |
| 366 | PhaserArcs | 0,107,5,10 mirror-V | Rear disruptor |
| 370 | PhaserArcs | 0,122,4,6 | Torpedo glyph |

The SDK indicator-overlay sprites (500–515 from
`PhaserFields.tga`) used to live here too but were dropped in
favour of a CSS in-arc stroke around the arc shape. The SDK
`SetIndicatorIcon*` setters still exist on `SubsystemProperty`
for SDK fidelity but the panel ignores them.

See `engine/ui/weapon_icons.py:ICON_REGISTRY` for the canonical
list.

## Starting from the auto-trace

If you want to use the runtime trace as the starting point for a
hand-edit, copy from the cache:

    cp cache/icons/weapons/350.svg native/assets/ui-cef/icons/weapons/

…then edit. The committed copy immediately takes precedence; the
cache stays available as the unedited reference.

## Rasterised reference

`reference/{num}.png` holds a 24-bit RGB PNG of each sprite at its
native pixel size, with the transparent atlas pixels flattened to
black so the sprite reads white-on-black like the BC HUD. These are
authoring references — not loaded at runtime — handy for tracing in
a vector editor or comparing the hand-authored SVG to the source.

Regenerate via:

    uv run python -c "from engine.ui.weapon_icons import export_reference_pngs; export_reference_pngs()"
