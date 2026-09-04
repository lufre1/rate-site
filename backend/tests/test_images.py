"""Unit tests for the upload metadata stripper.

These build the containers by hand rather than with an imaging library: the
production code has no Pillow dependency (see images.py), and the point of the
tests is the container parsing, not the pixels.

The synthetic fixtures below mirror the three shapes that actually turned up in
the live uploads directory: a plain JFIF+Exif JPEG, an Exif-bearing PNG, and --
the case that broke the first version of the stripper -- an iPhone-style file
with a second image appended after the primary EOI, whose APP1 the naive
"copy everything after SOS" approach preserved.
"""
import struct

from images import strip_metadata


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def _seg(marker: int, payload: bytes) -> bytes:
    """A length-bearing JPEG segment."""
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


EXIF_PAYLOAD = b"Exif\x00\x00" + b"MM\x00*" + b"\x00" * 40
XMP_PAYLOAD = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>secret</x:xmpmeta>"
ICC_PAYLOAD = b"ICC_PROFILE\x00" + b"\x01" * 32
SCAN = b"\x12\x34\xff\x00\x56\xff\xd0\x78"  # includes a stuffed FF and an RST


def _jpeg(*, exif=True, xmp=False, icc=True, comment=False, trailer=b"") -> bytes:
    parts = [b"\xff\xd8", _seg(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00")]
    if exif:
        parts.append(_seg(0xE1, EXIF_PAYLOAD))
    if xmp:
        parts.append(_seg(0xE1, XMP_PAYLOAD))
    if icc:
        parts.append(_seg(0xE2, ICC_PAYLOAD))
    if comment:
        parts.append(_seg(0xFE, b"a private comment"))
    parts.append(_seg(0xC0, b"\x08\x00\x10\x00\x10\x01\x11\x00"))  # SOF0
    parts.append(_seg(0xDA, b"\x01\x01\x00"))                      # SOS header
    parts.append(SCAN)
    parts.append(b"\xff\xd9")
    return b"".join(parts) + trailer


def _png_chunk(ctype: bytes, payload: bytes = b"") -> bytes:
    import zlib
    body = ctype + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _png(*, exif=True, text=True, trailer=b"") -> bytes:
    parts = [b"\x89PNG\r\n\x1a\n",
             _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))]
    if exif:
        parts.append(_png_chunk(b"eXIf", EXIF_PAYLOAD))
    if text:
        parts.append(_png_chunk(b"tEXt", b"Comment\x00private"))
        parts.append(_png_chunk(b"tIME", b"\x07\xe6\x01\x01\x00\x00\x00"))
    parts.append(_png_chunk(b"IDAT", b"\x08\xd7c\x00\x00\x00\x02\x00\x01"))
    parts.append(_png_chunk(b"IEND"))
    return b"".join(parts) + trailer


def _webp_chunk(ctype: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) & 1 else b""
    return ctype + struct.pack("<I", len(payload)) + payload + pad


def _webp(*, exif=True, xmp=True) -> bytes:
    # VP8X flag bits: 0b1000 = EXIF, 0b0100 = XMP.
    body = _webp_chunk(b"VP8X", b"\x0c\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    body += _webp_chunk(b"VP8 ", b"\x01" * 16)
    if exif:
        body += _webp_chunk(b"EXIF", EXIF_PAYLOAD)
    if xmp:
        body += _webp_chunk(b"XMP ", XMP_PAYLOAD)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------

def test_jpeg_exif_is_removed():
    out = strip_metadata(_jpeg(), ".jpg")
    assert b"Exif\x00\x00" not in out
    assert out.startswith(b"\xff\xd8")
    assert out.endswith(b"\xff\xd9")


def test_jpeg_xmp_and_comment_are_removed():
    out = strip_metadata(_jpeg(xmp=True, comment=True), ".jpeg")
    assert b"ns.adobe.com" not in out
    assert b"a private comment" not in out


def test_jpeg_keeps_the_icc_profile_and_jfif_header():
    """Dropping the ICC profile visibly shifts wide-gamut phone colours."""
    out = strip_metadata(_jpeg(), ".jpg")
    assert b"ICC_PROFILE" in out
    assert b"JFIF" in out


def test_jpeg_drops_the_mpf_index_but_keeps_icc():
    """Both live in APP2, so the choice is made on payload, not on marker.

    The MPF index describes the trailing images this function removes, so
    keeping it leaves a file advertising pictures it no longer contains --
    which is why Pillow still called a stripped iPhone photo an MPO.
    """
    mpf = b"MPF\x00" + b"MM\x00*" + b"\x00" * 40
    original = _jpeg(exif=False, icc=True)
    with_mpf = original[:2] + _seg(0xE2, mpf) + original[2:]
    out = strip_metadata(with_mpf, ".jpeg")
    assert b"MPF\x00" not in out
    assert b"ICC_PROFILE" in out


def test_jpeg_scan_data_survives_intact():
    """The entropy-coded scan is the image; it must pass through untouched."""
    out = strip_metadata(_jpeg(), ".jpg")
    assert SCAN in out


def test_jpeg_trailer_after_eoi_is_dropped():
    """The regression that mattered: an iPhone HDR gain map appended after EOI
    is a second JPEG with its own APP1, and copying the tail verbatim published
    it. 34 of 55 live photos kept their XMP this way."""
    hidden = _jpeg(exif=True, xmp=True, icc=False)
    out = strip_metadata(_jpeg(trailer=hidden), ".jpeg")
    assert b"ns.adobe.com" not in out
    assert b"Exif\x00\x00" not in out
    assert out.endswith(b"\xff\xd9")


def test_jpeg_without_metadata_is_returned_byte_identical():
    clean = _jpeg(exif=False, icc=False)
    assert strip_metadata(clean, ".jpg") == clean


def test_jpeg_output_is_never_larger():
    original = _jpeg(xmp=True, comment=True)
    assert len(strip_metadata(original, ".jpg")) <= len(original)


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------

def test_png_metadata_chunks_are_removed():
    out = strip_metadata(_png(), ".png")
    assert b"eXIf" not in out
    assert b"tEXt" not in out
    assert b"tIME" not in out
    assert b"IDAT" in out and b"IHDR" in out
    assert out.startswith(b"\x89PNG\r\n\x1a\n")


def test_png_trailer_after_iend_is_dropped():
    out = strip_metadata(_png(exif=False, text=False, trailer=b"\x00trailing junk"), ".png")
    assert b"trailing junk" not in out


def test_png_without_metadata_is_returned_byte_identical():
    clean = _png(exif=False, text=False)
    assert strip_metadata(clean, ".png") == clean


# --------------------------------------------------------------------------
# WebP
# --------------------------------------------------------------------------

def test_webp_exif_and_xmp_chunks_are_removed():
    out = strip_metadata(_webp(), ".webp")
    assert b"EXIF" not in out
    assert b"XMP " not in out
    assert b"VP8 " in out


def test_webp_riff_size_field_is_rewritten():
    out = strip_metadata(_webp(), ".webp")
    assert struct.unpack("<I", out[4:8])[0] == len(out) - 8


def test_webp_vp8x_flags_no_longer_advertise_removed_chunks():
    out = strip_metadata(_webp(), ".webp")
    flags = out[12 + 8]  # RIFF header + "VP8X" + length
    assert not flags & 0b00001000, "EXIF flag still set"
    assert not flags & 0b00000100, "XMP flag still set"


# --------------------------------------------------------------------------
# Fail-safe behaviour
# --------------------------------------------------------------------------

def test_unknown_extension_is_passed_through():
    assert strip_metadata(b"whatever", ".gif") == b"whatever"


def test_unparseable_file_is_passed_through_not_corrupted():
    """A broken upload must survive as-is rather than be mangled. Ten of the
    live uploads are non-image test artefacts that hit this path."""
    junk = b"this is not an image at all"
    assert strip_metadata(junk, ".jpg") == junk
    assert strip_metadata(junk, ".png") == junk
    assert strip_metadata(junk, ".webp") == junk


def test_truncated_jpeg_is_passed_through():
    truncated = _jpeg()[:20]
    assert strip_metadata(truncated, ".jpg") == truncated


def test_extension_matching_is_case_insensitive():
    out = strip_metadata(_jpeg(), ".JPG")
    assert b"Exif\x00\x00" not in out


def test_empty_input_does_not_raise():
    assert strip_metadata(b"", ".jpg") == b""
