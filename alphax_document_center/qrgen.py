# Copyright (c) 2026, Neotec Integrated Solution and contributors
# For license information, please see license.txt
#
# Self-contained QR Code encoder and PNG writer.
#
# Written because external QR libraries kept being the weak link:
#   - `qrcode` needs Pillow and is not a Frappe dependency.
#   - `pyqrcode` defaults to latin-1 and raises on Arabic text.
#   - `pyqrcode` without `pypng` emits SVG, which wkhtmltopdf cannot render.
# This module uses only the standard library (zlib, struct), always encodes in
# UTF-8 byte mode, and always outputs PNG. Nothing to install, nothing to
# break between environments.
#
# Supports versions 1-20, which covers ~850 bytes at EC level L - far beyond
# what an asset label needs.

import struct
import zlib

# ----------------------------------------------------------------------
# Reference tables (ISO/IEC 18004)
# ----------------------------------------------------------------------

# Total codewords (data + error correction) per version.
TOTAL_CODEWORDS = [
    0, 26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
    404, 466, 532, 581, 655, 733, 815, 901, 991, 1085,
]

# (error correction codewords per block, number of blocks) by version, level.
EC_TABLE = {
    1:  {"L": (7, 1),   "M": (10, 1),  "Q": (13, 1),  "H": (17, 1)},
    2:  {"L": (10, 1),  "M": (16, 1),  "Q": (22, 1),  "H": (28, 1)},
    3:  {"L": (15, 1),  "M": (26, 1),  "Q": (18, 2),  "H": (22, 2)},
    4:  {"L": (20, 1),  "M": (18, 2),  "Q": (26, 2),  "H": (16, 4)},
    5:  {"L": (26, 1),  "M": (24, 2),  "Q": (18, 4),  "H": (22, 4)},
    6:  {"L": (18, 2),  "M": (16, 4),  "Q": (24, 4),  "H": (28, 4)},
    7:  {"L": (20, 2),  "M": (18, 4),  "Q": (18, 6),  "H": (26, 5)},
    8:  {"L": (24, 2),  "M": (22, 4),  "Q": (22, 6),  "H": (26, 6)},
    9:  {"L": (30, 2),  "M": (22, 5),  "Q": (20, 8),  "H": (24, 8)},
    10: {"L": (18, 4),  "M": (26, 5),  "Q": (24, 8),  "H": (28, 8)},
    11: {"L": (20, 4),  "M": (30, 5),  "Q": (28, 8),  "H": (24, 11)},
    12: {"L": (24, 4),  "M": (22, 8),  "Q": (26, 10), "H": (28, 11)},
    13: {"L": (26, 4),  "M": (22, 9),  "Q": (24, 12), "H": (22, 16)},
    14: {"L": (30, 4),  "M": (24, 9),  "Q": (20, 16), "H": (24, 16)},
    15: {"L": (22, 6),  "M": (24, 10), "Q": (30, 12), "H": (24, 18)},
    16: {"L": (24, 6),  "M": (28, 10), "Q": (24, 17), "H": (30, 16)},
    17: {"L": (28, 6),  "M": (28, 11), "Q": (28, 16), "H": (28, 19)},
    18: {"L": (30, 6),  "M": (26, 13), "Q": (28, 18), "H": (28, 21)},
    19: {"L": (28, 7),  "M": (26, 14), "Q": (26, 21), "H": (26, 25)},
    20: {"L": (28, 8),  "M": (26, 16), "Q": (30, 20), "H": (28, 25)},
}

# Row/column centres of alignment patterns.
ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
    11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66],
    15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78],
    18: [6, 30, 56, 82], 19: [6, 30, 58, 86], 20: [6, 34, 62, 90],
}

EC_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

MAX_VERSION = 20


# ----------------------------------------------------------------------
# GF(256) arithmetic for Reed-Solomon
# ----------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D  # QR's primitive polynomial
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator_poly(degree):
    """Reed-Solomon generator polynomial, built rather than tabulated."""
    poly = [1]
    for i in range(degree):
        new = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            new[j] ^= _gf_mul(coef, 1)
            new[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = new
    return poly


def _ec_codewords(data, count):
    gen = _generator_poly(count)
    remainder = list(data) + [0] * count
    for i in range(len(data)):
        factor = remainder[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            remainder[i + j] ^= _gf_mul(g, factor)
    return remainder[len(data):]


# ----------------------------------------------------------------------
# Encoding
# ----------------------------------------------------------------------
def _capacity(version, level):
    ec_per_block, blocks = EC_TABLE[version][level]
    return TOTAL_CODEWORDS[version] - ec_per_block * blocks


def _choose_version(byte_len, level):
    for version in range(1, MAX_VERSION + 1):
        # 4 bits mode + length bits + payload
        length_bits = 8 if version <= 9 else 16
        needed = (4 + length_bits + byte_len * 8 + 7) // 8
        if needed <= _capacity(version, level):
            return version
    raise ValueError(
        f"{byte_len} bytes is too long for a version-{MAX_VERSION} QR code at level {level}."
    )


def _bitstream(data, version, level):
    length_bits = 8 if version <= 9 else 16
    bits = []

    def push(value, count):
        for i in range(count - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)                 # byte mode
    push(len(data), length_bits)
    for byte in data:
        push(byte, 8)

    capacity_bits = _capacity(version, level) * 8
    push(0, min(4, capacity_bits - len(bits)))          # terminator
    while len(bits) % 8:                                 # pad to byte boundary
        bits.append(0)

    codewords = [
        int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)
    ]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < _capacity(version, level):
        codewords.append(pad[i % 2])
        i += 1
    return codewords


def _interleave(codewords, version, level):
    ec_per_block, blocks = EC_TABLE[version][level]
    total_data = len(codewords)
    short_len = total_data // blocks
    long_blocks = total_data % blocks

    data_blocks, ec_blocks = [], []
    pos = 0
    for b in range(blocks):
        size = short_len + (1 if b >= blocks - long_blocks else 0)
        block = codewords[pos:pos + size]
        pos += size
        data_blocks.append(block)
        ec_blocks.append(_ec_codewords(block, ec_per_block))

    out = []
    for i in range(max(len(b) for b in data_blocks)):
        for block in data_blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            out.append(block[i])
    return out


# ----------------------------------------------------------------------
# Matrix construction
# ----------------------------------------------------------------------
def _new_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_finder(m, row, col):
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if not (0 <= rr < len(m) and 0 <= cc < len(m)):
                continue
            if 0 <= r <= 6 and 0 <= c <= 6:
                dark = (
                    r in (0, 6) or c in (0, 6)
                    or (2 <= r <= 4 and 2 <= c <= 4)
                )
            else:
                dark = False
            m[rr][cc] = 1 if dark else 0


def _place_alignment(m, version):
    centres = ALIGNMENT[version]
    size = len(m)
    for r in centres:
        for c in centres:
            # Skip the three corners occupied by finder patterns.
            if (r < 8 and c < 8) or (r < 8 and c > size - 9) or (r > size - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    dark = max(abs(dr), abs(dc)) != 1
                    m[r + dr][c + dc] = 1 if dark else 0


def _place_timing(m):
    size = len(m)
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        if m[6][i] is None:
            m[6][i] = bit
        if m[i][6] is None:
            m[i][6] = bit


def _reserve_format(m):
    size = len(m)
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = 0
        if m[i][8] is None:
            m[i][8] = 0
    for i in range(8):
        if m[8][size - 1 - i] is None:
            m[8][size - 1 - i] = 0
        if m[size - 1 - i][8] is None:
            m[size - 1 - i][8] = 0
    m[size - 8][8] = 1  # dark module


def _reserve_version(m, version):
    if version < 7:
        return
    size = len(m)
    for i in range(6):
        for j in range(3):
            if m[size - 11 + j][i] is None:
                m[size - 11 + j][i] = 0
            if m[i][size - 11 + j] is None:
                m[i][size - 11 + j] = 0


def _place_data(m, bits):
    size = len(m)
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # skip the vertical timing column
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if m[row][c] is None:
                    m[row][c] = bits[idx] if idx < len(bits) else 0
                    idx += 1
        upward = not upward
        col -= 2


MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _function_map(version, size):
    """Matrix marking which cells are function patterns (not maskable)."""
    fm = _new_matrix(size)
    _place_finder(fm, 0, 0)
    _place_finder(fm, 0, size - 7)
    _place_finder(fm, size - 7, 0)
    _place_alignment(fm, version)
    _place_timing(fm)
    _reserve_format(fm)
    _reserve_version(fm, version)
    return [[cell is not None for cell in row] for row in fm]


def _apply_mask(matrix, is_function, mask_id):
    size = len(matrix)
    out = [row[:] for row in matrix]
    fn = MASKS[mask_id]
    for r in range(size):
        for c in range(size):
            if not is_function[r][c] and fn(r, c):
                out[r][c] ^= 1
    return out


def _format_bits(level, mask_id):
    data = (EC_LEVEL_BITS[level] << 3) | mask_id
    value = data << 10
    gen = 0b10100110111
    for i in range(14, 9, -1):
        if value & (1 << i):
            value ^= gen << (i - 10)
    return ((data << 10) | value) ^ 0b101010000010010


def _version_bits(version):
    value = version << 12
    gen = 0b1111100100101
    for i in range(17, 11, -1):
        if value & (1 << i):
            value ^= gen << (i - 12)
    return (version << 12) | value


def _place_format(m, level, mask_id):
    """Write the 15-bit format information, twice.

    Note the orientation: the first copy runs DOWN column 8 for bits 0-5 and
    ALONG row 8 for bits 9-14. Transposing these two halves produces a QR that
    looks plausible but cannot be decoded at all, because a reader parses the
    format information before anything else.
    """
    size = len(m)
    bits = _format_bits(level, mask_id)

    def bit(i):
        return (bits >> i) & 1

    # Copy 1: around the top-left finder.
    for i in range(6):
        m[i][8] = bit(i)
    m[7][8] = bit(6)
    m[8][8] = bit(7)
    m[8][7] = bit(8)
    for i in range(9, 15):
        m[8][14 - i] = bit(i)

    # Copy 2: split between the bottom-left and top-right finders.
    for i in range(8):
        m[8][size - 1 - i] = bit(i)
    for i in range(8, 15):
        m[size - 15 + i][8] = bit(i)

    m[size - 8][8] = 1  # dark module


def _place_version(m, version):
    if version < 7:
        return
    size = len(m)
    bits = _version_bits(version)
    for i in range(18):
        bit = (bits >> i) & 1
        r, c = i // 3, i % 3
        m[size - 11 + c][r] = bit
        m[r][size - 11 + c] = bit


def _penalty(m):
    size = len(m)
    score = 0

    # Rule 1: runs of five or more same-coloured modules.
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for cell in line[1:]:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            score += 3 + (run - 5)

    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3

    # Rule 3: finder-like patterns.
    pattern_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pattern_b = list(reversed(pattern_a))
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == pattern_a or window == pattern_b:
                score += 40

    # Rule 4: overall dark/light balance.
    dark = sum(sum(row) for row in m)
    percent = dark * 100 // (size * size)
    score += 10 * min(abs(percent - 50) // 5, 20)
    return score


def make_matrix(text, level="L"):
    """Return the QR matrix (list of rows of 0/1) for `text`."""
    level = (level or "L").upper()
    if level not in EC_LEVEL_BITS:
        level = "L"

    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    version = _choose_version(len(data), level)
    size = version * 4 + 17

    codewords = _interleave(_bitstream(data, version, level), version, level)
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)

    base = _new_matrix(size)
    _place_finder(base, 0, 0)
    _place_finder(base, 0, size - 7)
    _place_finder(base, size - 7, 0)
    _place_alignment(base, version)
    _place_timing(base)
    _reserve_format(base)
    _reserve_version(base, version)
    _place_data(base, bits)

    is_function = _function_map(version, size)

    best, best_score = None, None
    for mask_id in range(8):
        candidate = _apply_mask(base, is_function, mask_id)
        _place_format(candidate, level, mask_id)
        _place_version(candidate, version)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


# ----------------------------------------------------------------------
# PNG output (stdlib only)
# ----------------------------------------------------------------------
def _png(matrix, scale=8, border=2):
    size = len(matrix)
    width = (size + border * 2) * scale

    rows = []
    blank = b"\xff" * width
    for _ in range(border * scale):
        rows.append(blank)
    for row in matrix:
        line = bytearray()
        line += b"\xff" * (border * scale)
        for cell in row:
            line += (b"\x00" if cell else b"\xff") * scale
        line += b"\xff" * (border * scale)
        for _ in range(scale):
            rows.append(bytes(line))
    for _ in range(border * scale):
        rows.append(blank)

    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    # 8-bit greyscale
    ihdr = struct.pack(">IIBBBBB", width, width, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def png_bytes(text, level="L", scale=8, border=2):
    """QR code for `text` as PNG bytes. Standard library only."""
    return _png(make_matrix(text, level=level), scale=scale, border=border)
