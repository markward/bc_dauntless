# 05 — Sensors / radar

Visual reference: [05-sensors-radar.html](05-sensors-radar.html)

The SCIENCE / F4 panel. A perspective-tilted radar disc with concentric range rings, cardinal axes, and blips for nearby ships / objects. Each blip's colour and shape encodes its affiliation + stem its altitude offset from the disc plane.

## Disc anatomy

```
            ╱  (above-plane stem, friendly NE)
        ▲
       ▲│
    ┌──┼──┐
   /   │   \
  /    ●    \      ● = player (white triangle at centre)
 │  ▼  │  ▲ │      ▼/▲ = blip facing direction; stem = altitude
  \    │    /
   \   │   /
    └──┼──┘
        │
        ▼  (below-plane stem, friendly W)
```

The disc itself is an ellipse (perspective foreshortening). Outer ring solid, middle + inner rings dashed. Cardinal cross-lines (N/S/E/W) faintly visible.

### Disc tokens

| Element | Token | Value |
|---|---|---|
| Disc inner | `--bc-sensor-disc-inner` | `rgba(15, 12, 35, 0.95)` |
| Disc outer (gradient end) | `--bc-sensor-disc-outer` | `rgba(8, 6, 22, 0.95)` |
| Outer ring (solid) | `--bc-sensor-ring` | `rgba(216, 94, 86, 0.7)` (Menu1 base, dimmed) |
| Middle ring (dashed) | `--bc-sensor-ring-mid` | `rgba(216, 94, 86, 0.4)` |
| Inner ring (dashed) | `--bc-sensor-ring-inner` | `rgba(216, 94, 86, 0.25)` |
| Cardinal cross | `--bc-sensor-cardinal` | `rgba(255, 255, 255, 0.08)` |

## Blip glyphs

A blip is a small triangle (or square for torpedoes / asteroids) plus an optional vertical stem indicating altitude relative to the disc plane. The triangle points in the contact's heading direction.

| Affiliation | Token | Value | Glyph |
|---|---|---|---|
| Player (self) | `--bc-sensor-player` | `#fff` (white) | Filled triangle, slightly larger |
| Friendly | `--bc-sensor-friendly` | `rgb(80, 170, 255)` (blue) | Triangle |
| Hostile | `--bc-sensor-hostile` | `rgb(220, 60, 60)` (red) | Triangle |
| Neutral | `--bc-sensor-neutral` | `rgb(255, 210, 90)` (gold) | Triangle |
| Torpedo / projectile | `--bc-sensor-neutral` (or per-shooter) | — | Filled square (no heading) |

### Stem semantics

- **No stem**: contact is in the disc plane.
- **Short upward stem**: slightly above plane.
- **Long upward stem**: far above plane.
- **Downward stem**: below plane (mirror upward).
- Stem colour matches the blip; line width 1 px.

### Target bracket

The currently-selected target gets a square gold bracket around its blip:
- Token: `--bc-sensor-target-bracket` `rgb(255, 210, 90)` (matches neutral / gold accent)
- 4 small line segments at the bracket corners, leaving the centre open so the blip glyph reads through

## Engine-rendered vs HTML-rendered

The mockup renders the disc as a static HTML/CSS perspective transform. In the **runtime**, this disc is **engine-rendered** by a C++ pass that:
1. Reads ship/torpedo positions from the world each frame
2. Projects them onto the disc plane (with altitude → stem length)
3. Rasterises blip glyphs + stems + bracket onto a texture
4. The texture is then displayed inside the panel body via a static `<img>` (or fed in as a continuously-updated `data-bind-image` attribute)

Static HTML + CSS is sufficient for the panel chrome and the legend. The disc-contents themselves are engine output.

## SDK runtime contract

```python
pRadar = App.RadarDisplay_Create(parent, ...)
pRadar.SetRange(8000)              # metres; disc outer ring = this range
pRadar.SetTrackedSet(g_kBattleSet) # which set's ships to plot
pRadar.SetActiveTarget(pEnemy)     # for the gold bracket
# Updates happen automatically per tick from the C++ side; no per-tick SDK call needed
# once the target / range / set are set.
```

## Legend

The mockup includes an optional legend below the disc with bullet-list explanations of glyphs ("Player ship - on the disc plane, fore=up", etc.). The legend is fixed text — no runtime updates. Implement only if there's screen real estate.
