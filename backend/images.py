"""Strip metadata out of uploaded images.

Photos are served publicly and cached for 30 days (see nginx-proxy.conf), so
anything left in the file is published. A phone JPEG carries an EXIF APP1
segment with the device make and model, the capture time to the second and,
depending on the camera settings, GPS coordinates. None of that has anything to
do with rating a canteen meal.

This works on the *container* rather than the image: it drops the metadata
segments and copies every other byte through untouched. That is why there is no
Pillow dependency here -- no decode, no re-encode, so no quality loss and no
memory spike on a 3.8 GiB VM (see AGENTS.md, "Host memory"). It also means the
pixel data comes out bit-identical to what the user uploaded.

Anything this module cannot parse is returned unchanged. A photo that keeps its
EXIF is a privacy bug; a photo corrupted by a half-understood parser is a
broken upload, which is worse. Stripping is not validation either way -- the
caller must still treat the bytes as untrusted image data.
"""

import logging
import struct

log = logging.getLogger("api")

# JPEG APP1 holds both Exif and XMP, APP13 holds Photoshop/IPTC, and COM is a
# free-text comment. APP0 (JFIF) is kept.
_JPEG_DROP = {0xE1, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8,
              0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xFE}

# APP2 is shared between the ICC colour profile and the MPF (Multi-Picture)
# index, so it is decided on payload rather than marker. The ICC profile stays
# -- dropping it visibly shifts the colours of a wide-gamut phone photo. The
# MPF index goes: it describes the trailing images this function removes, so
# keeping it leaves a file advertising pictures that are no longer in it, and
# it carries per-image attributes of its own.
_APP2_KEEP_PREFIX = b"ICC_PROFILE\x00"

# Markers with no length field, which therefore cannot be skipped by length.
_JPEG_STANDALONE = {0x01} | set(range(0xD0, 0xD8))  # TEM, RST0-RST7

_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}

_WEBP_DROP = {b"EXIF", b"XMP "}


def _scan_to_marker(data: bytes, i: int) -> int:
    """Offset of the next real marker at or after `i`, walking entropy data.

    Inside a scan a 0xFF byte is not necessarily a marker: the encoder stuffs
    0xFF 0x00 to encode a literal 0xFF, restart markers RST0-RST7 are expected
    mid-scan, and a run of 0xFF is legal fill. Anything else ends the scan.
    """
    n = len(data)
    while i < n - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        nxt = data[i + 1]
        if nxt == 0x00:            # stuffed literal 0xFF
            i += 2
        elif nxt == 0xFF:          # fill byte
            i += 1
        elif 0xD0 <= nxt <= 0xD7:  # restart marker
            i += 2
        else:
            return i
    return n


def _strip_jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")

    out = bytearray(b"\xff\xd8")
    i = 2
    n = len(data)

    while i < n:
        # A marker may be preceded by any number of 0xFF fill bytes.
        if data[i] != 0xFF:
            raise ValueError(f"expected a marker at offset {i}")
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            raise ValueError("truncated marker")
        marker = data[i]
        i += 1

        # EOI ends the primary image; anything after it is a trailer, and the
        # trailer is dropped. An iPhone HDR photo appends a whole second JPEG
        # there (the gain map) carrying its own APP1/XMP -- which is exactly
        # how XMP survived an earlier version of this function that copied the
        # tail through verbatim. A trailer is not part of the displayed image,
        # so discarding it costs nothing and removes a second metadata carrier.
        if marker == 0xD9:
            out += b"\xff\xd9"
            break

        if marker in _JPEG_STANDALONE:
            out += bytes((0xFF, marker))
            continue

        if i + 2 > n:
            raise ValueError("truncated segment length")
        seg_len = struct.unpack(">H", data[i:i + 2])[0]
        if seg_len < 2 or i + seg_len > n:
            raise ValueError("bad segment length")

        payload = data[i + 2:i + seg_len]
        drop = marker in _JPEG_DROP
        if marker == 0xE2 and not payload.startswith(_APP2_KEEP_PREFIX):
            drop = True  # MPF index, or an APP2 flavour we do not recognise

        if not drop:
            out += bytes((0xFF, marker))
            out += data[i:i + seg_len]
        i += seg_len

        # SOS carries a seg_len header, then raw entropy-coded data up to the
        # next marker. A progressive JPEG has several of these, so copy the
        # scan and carry on round the loop rather than bailing out here.
        if marker == 0xDA:
            end = _scan_to_marker(data, i)
            out += data[i:end]
            i = end

    return bytes(out)


def _strip_png(data: bytes) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(sig):
        raise ValueError("not a PNG")

    out = bytearray(sig)
    i = len(sig)
    n = len(data)

    while i + 8 <= n:
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        end = i + 12 + length  # length + type + payload + crc
        if end > n:
            raise ValueError("truncated chunk")
        if ctype not in _PNG_DROP:
            out += data[i:end]
        i = end
        if ctype == b"IEND":
            break  # drop any trailer, as for JPEG

    return bytes(out)


def _strip_webp(data: bytes) -> bytes:
    if not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise ValueError("not a WebP")

    out = bytearray()
    i = 12
    n = len(data)

    while i + 8 <= n:
        ctype = data[i:i + 4]
        length = struct.unpack("<I", data[i + 4:i + 8])[0]
        padded = length + (length & 1)  # RIFF chunks are even-aligned
        end = i + 8 + padded
        if end > n:
            raise ValueError("truncated chunk")
        if ctype not in _WEBP_DROP:
            out += data[i:end]
        i = end

    body = bytes(out)
    # A VP8X header advertises which optional chunks follow; with EXIF and XMP
    # gone its flag bits would lie. Bit 3 is EXIF, bit 2 is XMP.
    if body[:4] == b"VP8X" and len(body) >= 12:
        body = body[:8] + bytes((body[8] & ~0b00001100,)) + body[9:]

    size = 4 + len(body)  # "WEBP" + payload
    return b"RIFF" + struct.pack("<I", size) + b"WEBP" + body


_STRIPPERS = {
    ".jpg": _strip_jpeg,
    ".jpeg": _strip_jpeg,
    ".png": _strip_png,
    ".webp": _strip_webp,
}


def strip_metadata(data: bytes, ext: str) -> bytes:
    """Return `data` with its metadata segments removed.

    `ext` is a lower-case extension including the dot, as produced by
    os.path.splitext. An unknown extension or an unparseable file is returned
    unchanged, with a warning -- see the module docstring.
    """
    stripper = _STRIPPERS.get(ext.lower())
    if stripper is None:
        log.warning("no metadata stripper for extension %r; storing as uploaded", ext)
        return data
    try:
        return stripper(data)
    except (ValueError, struct.error, IndexError) as exc:
        log.warning("could not strip metadata from %s upload: %s", ext, exc)
        return data
