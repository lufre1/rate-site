"""Strip metadata out of uploaded images.

Photos are served publicly and cached for 30 days (see nginx-proxy.conf), so
anything left in the file is published. A phone JPEG carries an EXIF APP1
segment with the device make and model, the capture time to the second and,
depending on the camera settings, GPS coordinates. None of that has anything to
do with rating a canteen meal.

strip_metadata() works on the *container* rather than the image: it drops the
metadata segments and copies every other byte through untouched -- no decode,
no re-encode, so no quality loss and pixel data bit-identical to the upload.

Anything this module cannot parse is returned unchanged. A photo that keeps its
EXIF is a privacy bug; a photo corrupted by a half-understood parser is a
broken upload, which is worse. Stripping is not validation either way -- the
caller must still treat the bytes as untrusted image data.

RESIZING (render_upload, added 2026-09-14)

Stripping alone left a real problem: uploads were stored at full phone
resolution and served straight into a 120px (.review__photo) or 220px-tall
(.dish__photo) box. Measured on prod that day -- 81 files, 149 MB, average
1.84 MB, largest 4.8 MB -- and one logged page load pulled **31.1 MB across 15
images**. nginx recorded urt=0.037 against rt=50.638 on a single 4.5 MB JPEG:
the backend was instant and the client spent fifty seconds pulling bytes. That
is what made the site intermittently unreachable on campus WiFi.

render_upload() therefore returns two derivatives: a display image capped at
MAX_DISPLAY_EDGE for the lightbox, and a THUMB_EDGE thumbnail for the grid.

This does mean Pillow, and a decode, on a 3.8 GiB VM (see AGENTS.md, "Host
memory"). Three things keep that honest:

  * Image.draft() lets libjpeg do the downscale in the DCT domain, so a 4000px
    JPEG headed for 1600px is decoded at half scale and never fully expands.
  * MAX_DECODE_PIXELS rejects decompression bombs. The 5 MB upload cap bounds
    the *file*, not the pixel count -- a few MB of PNG can decode to gigabytes.
  * Every failure path falls back to strip_metadata() on the original bytes, so
    a Pillow that is missing, or an image it cannot read, degrades to exactly
    the previous behaviour instead of losing the upload.

Orientation is baked into the pixels before the EXIF goes. Stripping APP1
already discarded the Orientation tag, so a portrait phone photo was being
stored upright-tagged and displayed on its side; exif_transpose() fixes that.
"""

import io
import logging
import struct

log = logging.getLogger("api")

# Optional on purpose. If the wheel is missing, render_upload() degrades to
# strip_metadata() rather than taking every upload down with an ImportError.
try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - exercised by the fallback tests
    Image = ImageOps = None

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


# --------------------------------------------------------------------------
# Resizing
# --------------------------------------------------------------------------

# The lightbox is the only place the big version is ever seen, and it is bounded
# by the viewport. 1600px covers a 2x laptop display without storing a 12 MP
# original nobody looks at.
MAX_DISPLAY_EDGE = 1600

# .review__photo is 120x120 and .dish__photo 220px tall, so 240 covers both at
# 2x device pixel ratio.
THUMB_EDGE = 240

DISPLAY_QUALITY = 82
THUMB_QUALITY = 78

# A 5 MB PNG can decode to gigabytes; the upload cap bounds the file, not the
# raster. Anything above this is passed through undecoded rather than resized.
MAX_DECODE_PIXELS = 40_000_000

# Only formats strip_metadata() already understands, so the two stay in step.
_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}

# The only containers here that can hold a real animation. Everything else that
# reports more than one frame is a multi-frame STILL, and frame 0 is the photo.
#
# This distinction is load-bearing. Pillow identifies an iPhone JPEG as MPO
# (Multi-Picture Object) and reports n_frames=2, because the phone attaches its
# HDR gain map or second-lens shot as a second image. A bare `n_frames > 1`
# check therefore rejected 17 of the 81 photos on prod -- 40 MB of the exact
# 2-3 MB originals this whole change exists to shrink -- while quietly logging
# them as "animated". The extra frame is the same trailer _strip_jpeg already
# drops, so taking frame 0 loses nothing.
_ANIMATION_FORMATS = {"GIF", "WEBP"}


def _flatten_for_jpeg(img):
    """JPEG has no alpha channel, so composite onto white rather than black.

    img.convert("RGB") on an RGBA image drops the alpha and leaves the
    transparent pixels at whatever colour sat underneath, which for a PNG
    screenshot is usually black. A white background matches the page.
    """
    if img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode(img, fmt: str, icc: bytes | None, quality: int) -> bytes:
    buf = io.BytesIO()
    params = {}
    # Keep the ICC profile: dropping it visibly shifts the colours of a
    # wide-gamut phone photo, which is the same reason _strip_jpeg keeps APP2.
    if icc:
        params["icc_profile"] = icc
    if fmt == "JPEG":
        img = _flatten_for_jpeg(img)
        # progressive renders a low-frequency pass first, which is the whole
        # point on the slow links this change exists for.
        params.update(quality=quality, optimize=True, progressive=True)
    elif fmt == "WEBP":
        params.update(quality=quality, method=4)
    elif fmt == "PNG":
        params.update(optimize=True)
    img.save(buf, fmt, **params)
    return buf.getvalue()


def render_upload(data: bytes, ext: str):
    """Return `(display, thumb)` bytes for an uploaded image.

    `display` is the image to store under the upload's own name, capped at
    MAX_DISPLAY_EDGE. `thumb` is a THUMB_EDGE version for the grid, or None
    when no thumbnail could be produced -- the caller must cope with that,
    because every failure path here returns it.

    Both outputs go through strip_metadata() as well. Pillow does not copy EXIF
    into the files it writes, so that is belt and braces, but it means the
    privacy guarantee is enforced by the same audited code on every path.
    """
    stripped = strip_metadata(data, ext)
    fmt = _FORMATS.get(ext.lower())

    if fmt is None or Image is None:
        if Image is None:
            log.warning("Pillow unavailable; storing %s upload unresized", ext)
        return stripped, None

    try:
        img = Image.open(io.BytesIO(data))

        # An animated GIF/WebP flattens to its first frame under thumbnail(),
        # which silently destroys the upload. Leave it alone. A multi-frame
        # still (MPO) is not animated -- see _ANIMATION_FORMATS.
        if img.format in _ANIMATION_FORMATS and getattr(img, "n_frames", 1) > 1:
            log.info("animated %s upload left unresized", ext)
            return stripped, None

        w, h = img.size
        if w * h > MAX_DECODE_PIXELS:
            log.warning("%s upload is %dx%d (> %d pixels); storing unresized",
                        ext, w, h, MAX_DECODE_PIXELS)
            return stripped, None

        icc = img.info.get("icc_profile")
        orientation = img.getexif().get(0x0112, 1)

        # draft() before any pixel access: for JPEG this asks libjpeg to decode
        # at a reduced DCT scale, so the full-resolution raster never exists.
        # It is a no-op for the other formats.
        img.draft(None, (MAX_DISPLAY_EDGE, MAX_DISPLAY_EDGE))

        # Rotate the pixels while the EXIF that describes the rotation is still
        # attached -- strip_metadata() has already thrown it away in `stripped`.
        img = ImageOps.exif_transpose(img)

        display_img = img.copy()
        display_img.thumbnail((MAX_DISPLAY_EDGE, MAX_DISPLAY_EDGE), Image.LANCZOS)
        thumb_img = display_img.copy()
        thumb_img.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.LANCZOS)

        display = strip_metadata(_encode(display_img, fmt, icc, DISPLAY_QUALITY), ext)
        thumb = strip_metadata(_encode(thumb_img, fmt, icc, THUMB_QUALITY), ext)
    except Exception as exc:  # Pillow raises a wide and undocumented range
        log.warning("could not resize %s upload: %s; storing unresized", ext, exc)
        return stripped, None

    # Re-encoding a small image can make it bigger. Keep whichever is smaller,
    # but only when the pixels did not have to move: an image that needed
    # rotating must come from Pillow or it goes back to being sideways.
    if orientation in (1, None) and max(w, h) <= MAX_DISPLAY_EDGE \
            and len(stripped) <= len(display):
        display = stripped

    return display, thumb
