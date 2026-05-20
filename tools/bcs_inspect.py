"""Inspect a Bridge Commander .BCS save file.

A real .BCS save (the one produced by stbc.exe / Appc, not the Phase 1 JSON
shim in engine/appc/save_load.py) has three regions:

  1. A custom 'UtopiaSV' preamble — magic, UtopiaModule scalars, the
     campaign name, and the install/build paths.
  2. A fixed-record object table — uniform 34-byte records with a 5-byte
     `01 03 01 00 00` tag, an object id, two floats, and prev/next id
     references.
  3. A TGL-filename inventory followed by the bulk of the file: a Python
     pickle protocol-1 stream containing the saved Python state of the
     game (the 39 classes with __getstate__/__setstate__).

This tool walks the preamble and tables directly, then hands the trailing
pickle bytes to ``pickletools.dis`` so the opcode stream is human-readable.
It never tries to import the SDK classes the pickle references — opcodes
are decoded without resolving GLOBAL targets.

Usage:
    uv run python tools/bcs_inspect.py [path/to/save.BCS]
    uv run python tools/bcs_inspect.py path/to/save.BCS --pickle-out out.pkl
    uv run python tools/bcs_inspect.py path/to/save.BCS --dis-limit 5000
"""
import argparse
import io
import pathlib
import pickletools
import struct
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
DEFAULT_SAVE = PROJECT_ROOT / "game" / "saves" / "C-E8M1-Mark.BCS"

# UtopiaSV preamble layout (all little-endian):
#   pstr "UtopiaSV"        # 4-byte length + bytes (length includes trailing NUL)
#   <7f 2i> scalars        # UtopiaModule state: 7 floats + 2 ints (36 bytes)
#   24 bytes 0x00          # reserved/padding
#   pstr campaign-name     # e.g. "Maelstrom"
#   pstr install-dir       # e.g. "C:\Program Files\Activision\Bridge Commander"
#   pstr build-dir         # e.g. "D:\Build" (SDK build path, leaked into save)
#   <8x I>                 # 8 zero bytes + uint32 object-id high-water mark
PREAMBLE_PAD = 24
HWM_LEADING_ZEROS = 8

# Object table records: uniform 33 bytes, leading tag identifies them.
OBJECT_RECORD_TAG = b"\x01\x03\x01\x00\x00"
OBJECT_RECORD_SIZE = 33


def pstr(buf: bytes, off: int) -> tuple[int, str]:
    """Read a 4-byte LE length followed by that many bytes; strip trailing NUL.
    Return (new offset, decoded string)."""
    n = struct.unpack_from("<I", buf, off)[0]
    raw = buf[off + 4 : off + 4 + n]
    return off + 4 + n, raw.rstrip(b"\x00").decode("latin-1", "replace")


def parse_preamble(buf: bytes) -> tuple[int, dict]:
    """Parse the UtopiaSV preamble. Return (offset after preamble, fields)."""
    off, magic = pstr(buf, 0)
    if magic != "UtopiaSV":
        raise ValueError(f"unexpected magic {magic!r} — not a BCS save?")

    scalars = struct.unpack_from("<7f 2i", buf, off)
    off += struct.calcsize("<7f 2i")

    pad = buf[off : off + PREAMBLE_PAD]
    if pad != b"\x00" * PREAMBLE_PAD:
        # Not fatal — record what we saw so the caller can investigate.
        print(f"WARNING: preamble pad not all-zero: {pad.hex()}", file=sys.stderr)
    off += PREAMBLE_PAD

    off, campaign = pstr(buf, off)
    off, install_dir = pstr(buf, off)
    off, build_dir = pstr(buf, off)

    # 8 zero bytes, then a uint32 (object-id high-water mark / next-id allocator).
    leading = buf[off : off + HWM_LEADING_ZEROS]
    if leading != b"\x00" * HWM_LEADING_ZEROS:
        print(f"WARNING: bytes before id HWM not all-zero: {leading.hex()}",
              file=sys.stderr)
    off += HWM_LEADING_ZEROS
    id_hwm = struct.unpack_from("<I", buf, off)[0]
    off += 4

    fields = {
        "magic": magic,
        "scalars": scalars,
        "campaign": campaign,
        "install_dir": install_dir,
        "build_dir": build_dir,
        "id_hwm": id_hwm,
    }
    return off, fields


def parse_object_table(buf: bytes, off: int) -> tuple[int, list[dict]]:
    """Walk the contiguous run of 34-byte object records."""
    records = []
    while off + OBJECT_RECORD_SIZE <= len(buf) and \
            buf[off : off + 5] == OBJECT_RECORD_TAG:
        body = buf[off + 5 : off + OBJECT_RECORD_SIZE]
        # Layout (28 bytes, little-endian):
        #   uint32 id          — usually < id_hwm
        #   2 × float32 (f0,f1) — often (0,0); some records have e.g. (0.5,-1.0)
        #   2 × float32 (g0,g1) — usually equal; values like 19.99, 22.99
        #   uint32 prev_id     — = id - 1 in every sample so far
        #   uint32 next_id     — a reference to another record (graph edge)
        rec_id, f0, f1, g0, g1, prev_id, next_id = \
            struct.unpack_from("<I 2f 2f 2I", body)
        records.append({
            "offset": off,
            "id": rec_id,
            "f01": (f0, f1),
            "g01": (g0, g1),
            "prev_id": prev_id,
            "next_id": next_id,
        })
        off += OBJECT_RECORD_SIZE
    return off, records


def parse_tgl_table(buf: bytes, off: int) -> tuple[int, list[tuple[str, int]]]:
    """Read the TGL-filename inventory: uint32 count, then for each entry a
    pstr followed by a uint32 trailing value (use-count or flag)."""
    count = struct.unpack_from("<I", buf, off)[0]
    off += 4
    entries = []
    for _ in range(count):
        off, name = pstr(buf, off)
        trailing = struct.unpack_from("<I", buf, off)[0]
        off += 4
        entries.append((name, trailing))
    return off, entries


def find_trailing_pickle_run(buf: bytes, after: int) -> int:
    """Locate the start of the contiguous trailing pickle-blob run.

    The post-TGL region is dominated by ~1.8 MB of structured binary
    object state (with small pickle fragments embedded). It ends with a
    long contiguous run of tiny back-to-back pickle blobs (each
    typically 4–20 bytes, every blob terminated by '.' STOP). That run
    is the easiest part of the file to verify — we find its start by
    locating the earliest offset from which ``pickletools.dis`` can
    decode a complete blob, and from which every subsequent position
    also decodes cleanly (i.e. the run is contiguous to EOF).

    Coarse-scan in 4 KB strides forward from ``after``, then narrow
    backwards.
    """
    def dis_ok(off: int) -> bool:
        try:
            pickletools.dis(buf[off:], out=io.StringIO())
            return True
        except Exception:
            return False

    for off in range(after, len(buf), 4096):
        if dis_ok(off):
            for step in (256, 16, 1):
                while off - step >= after and dis_ok(off - step):
                    off -= step
            return off
    raise ValueError("no clean pickle run found after TGL table")


def walk_pickle_blobs(buf: bytes, start: int, limit: int | None = None):
    """Yield (offset, consumed_bytes, summary) for each back-to-back pickle
    blob from ``start`` to EOF. Stops at the first decode error or after
    ``limit`` blobs."""
    off = start
    n = 0
    while off < len(buf):
        f = io.BytesIO(buf[off:])
        ops = []
        try:
            for op, arg, _pos in pickletools.genops(f):
                ops.append((op.name, arg))
                if op.name == "STOP":
                    break
            else:
                # Stream ended without STOP — not a valid blob; stop walking.
                return
        except Exception as e:
            yield off, 0, f"<decode error: {type(e).__name__}: {e}>"
            return
        consumed = f.tell()
        # One-line summary: opcode names plus the first non-None arg.
        opnames = ",".join(name for name, _ in ops)
        sample_arg = next((a for _, a in ops if a is not None), None)
        if isinstance(sample_arg, bytes) and len(sample_arg) > 24:
            sample_arg = sample_arg[:24] + b"..."
        yield off, consumed, f"{opnames}  arg={sample_arg!r}"
        off += consumed
        n += 1
        if limit is not None and n >= limit:
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path", nargs="?", default=str(DEFAULT_SAVE),
        help="path to a .BCS save (default: game/saves/C-E8M1-Mark.BCS)",
    )
    parser.add_argument(
        "--records", type=int, default=8,
        help="how many object-table records to dump (default: 8; 0 to skip)",
    )
    parser.add_argument(
        "--blobs", type=int, default=20,
        help="how many trailing pickle blobs to summarise (default: 20; 0 = none)",
    )
    parser.add_argument(
        "--pickle-out", type=pathlib.Path, default=None,
        help="write the trailing pickle-blob run to this path for offline analysis",
    )
    args = parser.parse_args()

    buf = pathlib.Path(args.path).read_bytes()
    print(f"file: {args.path}  size: {len(buf):,} bytes\n")

    off, fields = parse_preamble(buf)
    print("─── Preamble (UtopiaSV) ───")
    print(f"  magic        : {fields['magic']!r}")
    f = fields["scalars"]
    print(f"  version-like : {f[0]:.6f}  (float, looks like game version)")
    print(f"  scalars      : {f[1:7]}  (6 floats — UtopiaModule config)")
    print(f"  int pair     : {f[7:]}")
    print(f"  campaign     : {fields['campaign']!r}")
    print(f"  install dir  : {fields['install_dir']!r}")
    print(f"  build dir    : {fields['build_dir']!r}")
    print(f"  id HWM       : {fields['id_hwm']:#x} ({fields['id_hwm']:,})")
    print(f"  preamble end : @ {off:#x}\n")

    off, records = parse_object_table(buf, off)
    print(f"─── Object table — {len(records)} records "
          f"({OBJECT_RECORD_SIZE} bytes each) ───")
    if records and args.records:
        print(f"  {'idx':>3}  {'@offset':>8}  {'id':>10}  "
              f"{'f0,f1':>20}  {'g0,g1':>22}    prev_id    next_id")
        for i, r in enumerate(records[: args.records]):
            f01 = "(%g, %g)" % r["f01"]
            g01 = "(%.3f, %.3f)" % r["g01"]
            print(f"  {i:>3}  {r['offset']:>#8x}  {r['id']:>#10x}  "
                  f"{f01:>20}  {g01:>22}  "
                  f"{r['prev_id']:>#10x} {r['next_id']:>#10x}")
        if len(records) > args.records:
            print(f"  ... {len(records) - args.records} more records elided")

    # id-HWM sanity: every record id should be < HWM (HWM is the next-id allocator).
    if records:
        max_id = max(r["id"] for r in records)
        assert max_id < fields["id_hwm"], \
            f"record id {max_id:#x} exceeds HWM {fields['id_hwm']:#x}"

    print(f"  object table end : @ {off:#x}")

    # 1-byte zero separator between the record table and the TGL count.
    if buf[off:off + 1] == b"\x00":
        off += 1
    print(f"  TGL section starts : @ {off:#x}\n")

    off, tgl = parse_tgl_table(buf, off)
    print(f"─── TGL inventory — {len(tgl)} entries ───")
    for name, trailing in tgl:
        print(f"  {trailing:>4}  {name}")
    print(f"  tgl end : @ {off:#x}\n")

    pickle_start = find_trailing_pickle_run(buf, off)
    obj_state_size = pickle_start - off
    print(f"─── Object-state region (binary + embedded pickle, undecoded) ───")
    print(f"  start @ {off:#x}, end @ {pickle_start:#x}, "
          f"size = {obj_state_size:,} bytes "
          f"({obj_state_size / len(buf) * 100:.1f}% of file)")
    print(f"  first 32 bytes  : {buf[off:off+32].hex(' ')}")
    print(f"  last 32 bytes   : {buf[pickle_start-32:pickle_start].hex(' ')}\n")

    print(f"─── Trailing pickle-blob run ───")
    print(f"  starts @ {pickle_start:#x}, "
          f"size = {len(buf) - pickle_start:,} bytes "
          f"({(len(buf) - pickle_start) / len(buf) * 100:.1f}% of file)")
    # Walk all blobs in the run to count + size them.
    total_blobs = 0
    total_bytes = 0
    blob_summaries = []
    for blob_off, consumed, summary in walk_pickle_blobs(buf, pickle_start):
        total_blobs += 1
        total_bytes += consumed
        if total_blobs <= args.blobs:
            blob_summaries.append((blob_off, consumed, summary))
    print(f"  total blobs    : {total_blobs:,}")
    print(f"  avg blob size  : {total_bytes / max(total_blobs, 1):.1f} bytes")
    print(f"  last 16 bytes  : {buf[-16:].hex()}\n")

    if blob_summaries and args.blobs:
        print(f"─── First {len(blob_summaries)} pickle blobs ───")
        for blob_off, consumed, summary in blob_summaries:
            print(f"  @{blob_off:#08x}  +{consumed:3d}  {summary}")
        if total_blobs > args.blobs:
            print(f"  ... {total_blobs - args.blobs:,} more blobs elided "
                  f"(re-run with --blobs N)")

    if args.pickle_out is not None:
        args.pickle_out.write_bytes(buf[pickle_start:])
        print(f"\nwrote trailing pickle-blob run to {args.pickle_out}")


if __name__ == "__main__":
    main()
