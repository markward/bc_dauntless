# Canonical Dump Format (NIF v3.1)

Used by snapshot tests to detect parser regressions. Per the v3.1 amendment,
the dump is no longer used to compare against an external oracle; it's used
as a stable text representation that can be diffed against committed golden
files.

## Rules

1. **Line-oriented.** Every field is on its own line.
2. **Indentation:** two spaces per level. The file header is level 0; blocks
   are level 1; block fields are level 2; nested structs are level 3+.
3. **Floats** printed via `%.6g` (six significant digits).
4. **Vec3** as `(x, y, z)`.
5. **Mat3x3** as three lines of three components each.
6. **Strings** quoted with `"..."`, embedded quotes escaped as `\"`.
7. **Block IDs** as decimal integers; null reference = `null`.
8. **Block headers:** `block <index> <type-name>` no trailing colon.
9. **Field lines:** `<field-name>: <value>`.

## Example (v3.1)

```
file
  version: 0x03010000
  num_header_lines: 4
  num_blocks: 12
  block 0 NiNode
    name: "Top Level Object"
    flags: 0x000e
    translation: (0, 0, 0)
    rotation:
      (1, 0, 0)
      (0, 1, 0)
      (0, 0, 1)
    scale: 1
  block 1 NiTriShape
    ...
  block 11 End Of File
```
