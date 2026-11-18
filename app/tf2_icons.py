"""Copies TF2's scoreboard class icons out of your own TF2 install as small PNGs.

They live in tf2_textures_dir.vpk as Valve texture files (VTF), which Tk can't
show, so this reads the archive, decodes the texture and writes a 16x16 PNG.
"""

import os
import struct
import zlib

ICON_SIZE = 20
# Scanner class name -> name in TF2's files (materials/hud/leaderboard_class_<name>.vtf)
CLASS_FILES = {"Scout": "scout", "Soldier": "soldier", "Pyro": "pyro", "Demo": "demo", "Heavy": "heavy",
               "Engineer": "engineer", "Medic": "medic", "Sniper": "sniper", "Spy": "spy"}


# --- VPK archives -----------------------------------------------------------------

def _cstring(f):
    out = bytearray()
    while (c := f.read(1)) not in (b"\0", b""):
        out += c
    return out.decode("utf-8", "replace")


def read_from_vpk(dir_vpk, wanted):
    """{path: bytes} for the wanted paths in a Valve VPK archive."""
    found = {}
    with open(dir_vpk, "rb") as f:
        signature, version, tree_size = struct.unpack("<III", f.read(12))
        if signature != 0x55AA1234:
            raise ValueError("not a VPK archive")
        header = 12 if version == 1 else 28
        f.seek(header)
        while ext := _cstring(f):
            while folder := _cstring(f):
                while name := _cstring(f):
                    _, preload, archive, offset, length, _ = struct.unpack("<IHHIIH", f.read(18))
                    data = f.read(preload)
                    path = f"{folder}/{name}.{ext}"
                    if path in wanted:
                        found[path] = (data, archive, offset, length)
    result = {}
    for path, (data, archive, offset, length) in found.items():
        if archive == 0x7FFF:  # stored in the _dir file itself, right after the tree
            source, offset = dir_vpk, header + tree_size + offset
        else:
            source = dir_vpk.replace("_dir.vpk", f"_{archive:03d}.vpk")
        with open(source, "rb") as f:
            f.seek(offset)
            result[path] = data + f.read(length)
    return result


# --- VTF textures -------------------------------------------------------------------

def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _dxt(data, w, h, kind):
    """Decodes DXT1/DXT5 block compression to RGBA rows."""
    out = bytearray(w * h * 4)
    pos = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alphas = None
            if kind == 5:
                a0, a1 = data[pos], data[pos + 1]
                bits = int.from_bytes(data[pos + 2:pos + 8], "little")
                if a0 > a1:
                    table = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
                else:
                    table = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
                alphas = [table[(bits >> (3 * i)) & 7] for i in range(16)]
                pos += 8
            c0, c1, idx = struct.unpack_from("<HHI", data, pos)
            pos += 8
            p0, p1 = _rgb565(c0), _rgb565(c1)
            if kind == 5 or c0 > c1:
                colors = [p0 + (255,), p1 + (255,),
                          tuple((2 * a + b) // 3 for a, b in zip(p0, p1)) + (255,),
                          tuple((a + 2 * b) // 3 for a, b in zip(p0, p1)) + (255,)]
            else:
                colors = [p0 + (255,), p1 + (255,),
                          tuple((a + b) // 2 for a, b in zip(p0, p1)) + (255,), (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x < w and y < h:
                    r, g, b, a = colors[(idx >> (2 * i)) & 3]
                    if alphas:
                        a = alphas[i]
                    out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes((r, g, b, a))
    return bytes(out)


def decode_vtf(data):
    """(width, height, RGBA bytes) of a VTF texture's full-size image."""
    if data[:4] != b"VTF\0":
        raise ValueError("not a VTF texture")
    w, h = struct.unpack_from("<HH", data, 16)
    fmt = struct.unpack_from("<I", data, 52)[0]
    blocks = max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
    sizes = {13: blocks * 8, 15: blocks * 16, 12: w * h * 4, 0: w * h * 4}
    if fmt not in sizes:
        raise ValueError(f"unsupported VTF format {fmt}")
    pixels = data[-sizes[fmt]:]  # mipmaps go small to large, so the full size is last
    if fmt == 13:
        return w, h, _dxt(pixels, w, h, 1)
    if fmt == 15:
        return w, h, _dxt(pixels, w, h, 5)
    if fmt == 12:  # BGRA
        out = bytearray(pixels)
        out[0::4], out[2::4] = pixels[2::4], pixels[0::4]
        return w, h, bytes(out)
    return w, h, pixels  # RGBA


# --- PNG ---------------------------------------------------------------------------------

def shrink(w, h, rgba, size):
    """Area-averages an RGBA image down to size x size (any ratio), weighting
    colors by alpha so transparent edges don't darken."""
    sx, sy = w / size, h / size
    out = bytearray(size * size * 4)
    for y in range(size):
        y0, y1 = y * sy, (y + 1) * sy
        for x in range(size):
            x0, x1 = x * sx, (x + 1) * sx
            r = g = b = a = area = 0.0
            for yy in range(int(y0), min(h, int(y1 + 0.999))):
                wy = min(y1, yy + 1) - max(y0, yy)
                for xx in range(int(x0), min(w, int(x1 + 0.999))):
                    weight = wy * (min(x1, xx + 1) - max(x0, xx))
                    i = (yy * w + xx) * 4
                    pa = rgba[i + 3] * weight
                    r += rgba[i] * pa
                    g += rgba[i + 1] * pa
                    b += rgba[i + 2] * pa
                    a += pa
                    area += weight
            o = (y * size + x) * 4
            out[o:o + 4] = (bytes((int(r / a), int(g / a), int(b / a), int(a / area)))
                            if a else bytes(4))
    return bytes(out)


def write_png(path, w, h, rgba):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def extract_class_icons(tf_dir, out_dir):
    """{class: png path}, extracting from TF2 the first time only."""
    # The size is in the name, so changing ICON_SIZE makes fresh ones.
    paths = {cls: os.path.join(out_dir, f"{cls}-{ICON_SIZE}px.png") for cls in CLASS_FILES}
    if all(os.path.exists(p) for p in paths.values()):
        return paths
    wanted = {f"materials/hud/leaderboard_class_{name}.vtf": cls for cls, name in CLASS_FILES.items()}
    textures = read_from_vpk(os.path.join(tf_dir, "tf2_textures_dir.vpk"), set(wanted))
    os.makedirs(out_dir, exist_ok=True)
    for vpk_path, data in textures.items():
        w, h, rgba = decode_vtf(data)
        if w > ICON_SIZE:
            rgba, w, h = shrink(w, h, rgba, ICON_SIZE), ICON_SIZE, ICON_SIZE
        write_png(paths[wanted[vpk_path]], w, h, rgba)
    return {cls: p for cls, p in paths.items() if os.path.exists(p)}
