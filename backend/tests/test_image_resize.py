"""Unit tests for render_upload(), the resize half of backend/images.py.

test_images.py builds its fixtures by hand because the stripper is about
container parsing. These are about pixels, so they use Pillow -- the same
dependency the production path now has.

The contract under test is the one the 2026-09-14 investigation needed: a phone
photo must come out small enough to send over campus WiFi, a thumbnail must
exist for the grid, and every path that cannot deliver that must still return
an intact, metadata-free image rather than losing the upload.
"""
import io

import pytest

from images import (
    MAX_DECODE_PIXELS, MAX_DISPLAY_EDGE, THUMB_EDGE, render_upload,
)

PIL = pytest.importorskip("PIL", reason="Pillow is optional; render_upload degrades without it")
from PIL import Image  # noqa: E402


def _gradient(w, h, mode="RGB"):
    """A plausible photo: a gradient, so JPEG has something to compress."""
    img = Image.new(mode, (w, h))
    px = img.load()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            v = (x * 255 // max(w, 1), y * 255 // max(h, 1), (x + y) % 256)
            for dy in range(min(4, h - y)):
                for dx in range(min(4, w - x)):
                    px[x + dx, y + dy] = v + ((255,) if mode == "RGBA" else ())
    return img


def _photo(w, h, fmt="JPEG", mode="RGB", exif=None, **save):
    buf = io.BytesIO()
    if exif is not None:
        save["exif"] = exif
    _gradient(w, h, mode).save(buf, fmt, **save)
    return buf.getvalue()


def _size(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# --------------------------------------------------------------------------
# The main path
# --------------------------------------------------------------------------

def test_oversized_photo_is_capped_at_the_display_edge():
    display, thumb = render_upload(_photo(3000, 2000), ".jpg")
    assert max(_size(display)) == MAX_DISPLAY_EDGE
    assert thumb is not None


def test_thumbnail_is_produced_at_the_thumb_edge():
    _, thumb = render_upload(_photo(3000, 2000), ".jpg")
    assert max(_size(thumb)) == THUMB_EDGE


def test_aspect_ratio_is_preserved():
    display, thumb = render_upload(_photo(3000, 1500), ".jpg")
    for out in (display, thumb):
        w, h = _size(out)
        assert abs(w / h - 2.0) < 0.02


def test_the_whole_point_the_result_is_dramatically_smaller():
    """A 12 MP phone photo has to stop being a multi-megabyte download."""
    raw = _photo(4000, 3000, quality=95)
    display, thumb = render_upload(raw, ".jpg")
    assert len(display) < len(raw) / 4
    # The grid is what loads 15 of these at once; it is the number that made
    # one page load 31 MB.
    assert len(thumb) < 60 * 1024


def test_small_photo_is_not_upscaled():
    display, thumb = render_upload(_photo(320, 240), ".jpg")
    assert _size(display) == (320, 240)
    assert max(_size(thumb)) <= THUMB_EDGE


def test_a_small_photo_is_never_made_bigger_by_re_encoding():
    raw = _photo(200, 150, quality=30)
    display, _ = render_upload(raw, ".jpg")
    assert len(display) <= len(raw)


# --------------------------------------------------------------------------
# Metadata and orientation
# --------------------------------------------------------------------------

def test_exif_is_gone_from_both_outputs():
    exif = Image.Exif()
    exif[0x010F] = "ACME Phone"          # Make
    exif[0x9003] = "2026:09:14 12:00:00"  # DateTimeOriginal
    raw = _photo(2000, 1500, exif=exif.tobytes())
    assert b"ACME Phone" in raw

    display, thumb = render_upload(raw, ".jpg")
    for out in (display, thumb):
        assert b"Exif\x00\x00" not in out
        assert b"ACME Phone" not in out


def test_orientation_is_baked_into_the_pixels():
    """Stripping APP1 discarded the Orientation tag, so a portrait phone photo
    was stored upright-tagged and displayed on its side. Rotate first."""
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW for display
    raw = _photo(400, 200, exif=exif.tobytes())
    assert _size(raw) == (400, 200)

    display, _ = render_upload(raw, ".jpg")
    assert _size(display) == (200, 400)


def test_icc_profile_survives_the_re_encode():
    """Dropping it visibly shifts wide-gamut phone colours -- same reason
    _strip_jpeg keeps APP2."""
    icc = b"\x00\x00\x02\x0c" + b"acsp" + b"\x00" * 120
    raw = _photo(2000, 1500, icc_profile=icc)
    display, thumb = render_upload(raw, ".jpg")
    for out in (display, thumb):
        assert b"ICC_PROFILE" in out


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------

def test_png_stays_png_and_keeps_its_alpha():
    raw = _photo(1800, 1200, fmt="PNG", mode="RGBA")
    display, thumb = render_upload(raw, ".png")
    for out in (display, thumb):
        with Image.open(io.BytesIO(out)) as im:
            assert im.format == "PNG"
            assert im.mode in ("RGBA", "LA", "P")


def test_webp_stays_webp():
    raw = _photo(1800, 1200, fmt="WEBP")
    display, thumb = render_upload(raw, ".webp")
    for out in (display, thumb):
        with Image.open(io.BytesIO(out)) as im:
            assert im.format == "WEBP"


def test_mpo_still_is_resized_not_mistaken_for_an_animation():
    """The regression that left 17 of 81 prod photos at full size.

    Pillow identifies an iPhone JPEG as MPO and reports n_frames=2, because the
    phone attaches an HDR gain map as a second image. A bare `n_frames > 1`
    guard treated that as an animation and skipped the resize -- silently, at
    log level INFO -- on 40 MB of exactly the 2-3 MB originals this code exists
    to shrink.
    """
    # A real MPO: two JPEGs plus the MPF APP2 index that declares them. Pillow
    # needs that index to classify the file as MPO rather than plain JPEG.
    buf = io.BytesIO()
    _gradient(3000, 2000).save(
        buf, "MPO", save_all=True, append_images=[_gradient(600, 400)])
    raw = buf.getvalue()
    with Image.open(io.BytesIO(raw)) as probe:
        assert probe.format == "MPO", "fixture is not an MPO"
        assert probe.n_frames == 2

    display, thumb = render_upload(raw, ".jpeg")
    assert thumb is not None, "MPO was skipped as if it were animated"
    assert max(_size(display)) == MAX_DISPLAY_EDGE
    assert max(_size(thumb)) == THUMB_EDGE
    # Frame 0 is the photo; the gain map must not come through as the image.
    assert _size(display)[0] > _size(display)[1]


def test_animated_webp_is_left_alone():
    """thumbnail() would flatten it to frame one, destroying the upload."""
    frames = [Image.new("RGB", (600, 400), c) for c in ("red", "blue", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    raw = buf.getvalue()

    display, thumb = render_upload(raw, ".webp")
    assert thumb is None
    with Image.open(io.BytesIO(display)) as im:
        assert getattr(im, "n_frames", 1) == 3


# --------------------------------------------------------------------------
# Every failure has to degrade to "the old behaviour", not "no upload"
# --------------------------------------------------------------------------

def test_unparseable_bytes_fall_back_to_the_stripper():
    junk = b"\xff\xd8" + b"not really a jpeg" * 10
    display, thumb = render_upload(junk, ".jpg")
    assert thumb is None
    assert display  # intact, just not resized


def test_unknown_extension_is_passed_through_untouched():
    display, thumb = render_upload(b"whatever", ".gif")
    assert display == b"whatever"
    assert thumb is None


def test_empty_input_does_not_raise():
    display, thumb = render_upload(b"", ".jpg")
    assert display == b""
    assert thumb is None


def test_decompression_bomb_is_not_decoded(monkeypatch):
    """The 5 MB upload cap bounds the file, not the raster."""
    import images
    monkeypatch.setattr(images, "MAX_DECODE_PIXELS", 1000)
    raw = _photo(400, 300)
    display, thumb = render_upload(raw, ".jpg")
    assert thumb is None
    assert _size(display) == (400, 300)  # stored as-is, never expanded
    assert MAX_DECODE_PIXELS > 1000      # the real ceiling is not this low


def test_pillow_missing_degrades_to_stripping(monkeypatch):
    import images
    monkeypatch.setattr(images, "Image", None)
    raw = _photo(3000, 2000)
    display, thumb = render_upload(raw, ".jpg")
    assert thumb is None
    assert _size(display) == (3000, 2000)
