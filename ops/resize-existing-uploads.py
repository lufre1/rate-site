#!/usr/bin/env python3
"""One-off: resize photos uploaded before render_upload() existed.

Until 2026-09-14 uploads were stored at full phone resolution and served
straight into a 120px (.review__photo) or 220px-tall (.dish__photo) box.
Measured on prod that day: 81 files, 149 MB, average 1.84 MB, largest 4.8 MB.
One page load in the nginx log pulled 31.1 MB across 15 images, and a single
4.5 MB JPEG logged urt=0.037 against rt=50.638 -- the backend was instant and
the client spent fifty seconds pulling bytes. That is the timeout.

New uploads are handled by render_upload() in the upload handler; this fixes
the backlog. Three files come out of each input:

  * the display copy, rewritten IN PLACE under its existing name, because
    ratings.photo_url points at it -- renaming would break every stored URL;
  * a card copy at cards/<same name>, which is what the grid dish photo
    requests (added for #42: the old 240px thumb was upscaled into a ~361px
    card);
  * a thumbnail at thumbs/<same name>, which is what the 120px review photos
    request.

    ./ops/resize-existing-uploads.py                 # dry run, prod uploads
    ./ops/resize-existing-uploads.py --apply
    ./ops/resize-existing-uploads.py --dir /some/where --apply

Take a backup first (ops/backup.sh tars the uploads directory). Writes are
atomic -- a temp file in the same directory, then os.replace -- so an
interrupted run cannot leave a half-written photo where a valid one was.

Re-running is safe: a file already within MAX_DISPLAY_EDGE that already has
both derived copies is skipped, so a second pass cannot re-encode it a second
time and stack up generational JPEG loss. A file that only lacks the card copy
(the state every upload was in before #42) keeps its stored display bytes --
only the derived copies are written.
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from images import (  # noqa: E402
    CARD_EDGE, MAX_DISPLAY_EDGE, THUMB_EDGE, Image, render_upload,
)

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "uploads")
KNOWN_EXT = {".jpg", ".jpeg", ".png", ".webp"}
THUMB_SUBDIR = "thumbs"
CARD_SUBDIR = "cards"


def _write_atomic(path: str, data: bytes, mode: int | None) -> None:
    tmp = path + ".resizing"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    # Keep the original mode; a fresh temp file would be 0600 and nginx serves
    # these as a different user.
    os.chmod(tmp, mode if mode is not None else 0o644)
    os.replace(tmp, path)


def _dimensions(data: bytes):
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR, help="uploads directory")
    ap.add_argument("--apply", action="store_true",
                    help="actually rewrite the files (default is a dry run)")
    args = ap.parse_args()

    if Image is None:
        sys.exit("Pillow is not installed; nothing to do (see backend/requirements.txt)")

    updir = os.path.abspath(args.dir)
    if not os.path.isdir(updir):
        sys.exit(f"not a directory: {updir}")
    thumbdir = os.path.join(updir, THUMB_SUBDIR)
    carddir = os.path.join(updir, CARD_SUBDIR)

    print(f"{'REWRITING' if args.apply else 'DRY RUN  '}  {updir}")
    print(f"display <= {MAX_DISPLAY_EDGE}px, cards <= {CARD_EDGE}px -> {carddir}")
    print(f"thumbs <= {THUMB_EDGE}px -> {thumbdir}\n")

    if args.apply:
        os.makedirs(thumbdir, exist_ok=True)
        os.makedirs(carddir, exist_ok=True)

    changed = failed = skipped = nothumb = 0
    before = after = 0

    for name in sorted(os.listdir(updir)):
        path = os.path.join(updir, name)
        if not os.path.isfile(path):
            continue  # the thumbs/ and cards/ subdirectories themselves
        ext = os.path.splitext(name)[1].lower()
        if ext not in KNOWN_EXT:
            print(f"  skip     {name}  (unsupported extension)")
            skipped += 1
            continue

        raw = open(path, "rb").read()
        thumb_path = os.path.join(thumbdir, name)
        card_path = os.path.join(carddir, name)

        size = _dimensions(raw)
        if size and max(size) <= MAX_DISPLAY_EDGE \
                and os.path.isfile(thumb_path) and os.path.isfile(card_path):
            skipped += 1
            continue

        display, thumb, card = render_upload(raw, ext)

        if thumb is None or card is None:
            # render_upload could not decode it. It still returns the stripped
            # original, so the photo is intact -- it just stays big, and the
            # frontend falls back to it. Worth naming, not worth failing on.
            print(f"  NOTHUMB  {name}  (could not decode; left at {len(raw) / 1024:.0f} KiB)")
            nothumb += 1
            continue

        if size and max(size) <= MAX_DISPLAY_EDGE:
            # Nothing to do to the display copy: it is already what the lightbox
            # needs, and re-encoding it would only lose a generation. This is
            # the state of every upload made after 2026-09-14 -- they are
            # missing only the card copy added for #42.
            display = raw

        before += len(raw)
        after += len(display) + len(thumb) + len(card)
        changed += 1
        dims = f"{size[0]}x{size[1]}" if size else "?"
        print(f"  {'resize  ' if args.apply else 'would   '} {name}  {dims}  "
              f"{len(raw) / 1024:.0f} KiB -> {len(display) / 1024:.0f} KiB "
              f"+ {len(card) / 1024:.0f} KiB card + {len(thumb) / 1024:.0f} KiB thumb")

        if args.apply:
            mode = os.stat(path).st_mode & 0o7777
            # Derived copies first: if the run dies between the writes, the grid
            # has copies that match a photo that is merely still large. The
            # other order leaves a shrunk photo with no thumbnail.
            _write_atomic(card_path, card, mode)
            _write_atomic(thumb_path, thumb, mode)
            if display is not raw:
                _write_atomic(path, display, mode)

    total = f"{before / 1048576:.1f} MB of originals -> {after / 1048576:.1f} MB stored"
    print(f"\n{changed} file(s) {'rewritten' if args.apply else 'would change'}, "
          f"{skipped} already done or unsupported, {nothumb} undecodable, {failed} failed")
    print(total)
    if not args.apply and changed:
        print("\nRe-run with --apply to write. Back up first: ops/backup.sh")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
