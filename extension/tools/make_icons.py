"""Generate simple PNG icons for the extension (no external deps)."""
import struct, zlib, os

def make_icon(size, path):
    # Blue circle with a white "?"-like tick: simple two-tone design.
    bg = (79, 140, 255, 255)      # accent blue
    fg = (255, 255, 255, 255)     # white
    cx = cy = (size - 1) / 2
    r_outer = size * 0.46

    rows = []
    for y in range(size):
        row = bytearray()
        row.append(0)  # filter type 0
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= r_outer:
                # Inner question-mark dot: small filled circle lower-middle.
                dot_dx, dot_dy = x - cx, y - size * 0.62
                if (dot_dx * dot_dx + dot_dy * dot_dy) ** 0.5 <= size * 0.07:
                    row.extend(fg)
                # Curved stem of the question mark (approximate arc).
                elif size * 0.12 <= dist <= size * 0.22 and y < size * 0.55 and x > cx:
                    row.extend(fg)
                elif abs(dx) <= size * 0.045 and size * 0.42 <= y <= size * 0.55:
                    row.extend(fg)
                else:
                    row.extend(bg)
            else:
                row.extend((0, 0, 0, 0))
        rows.append(bytes(row))

    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    chunks = [
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", ihdr),
        chunk(b"IDAT", zlib.compress(raw)),
        chunk(b"IEND", b""),
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"".join(chunks))
    print(f"wrote {path}")

def chunk(ctype, data):
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )

base = os.path.join(os.path.dirname(__file__), "icons")
for s in (16, 32, 48, 128):
    make_icon(s, os.path.join(base, f"icon{s}.png"))
