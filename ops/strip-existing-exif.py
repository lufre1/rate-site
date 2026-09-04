#!/usr/bin/env python3
"""One-off: strip metadata from photos uploaded before images.py existed.

Uploads made before 2026-09-02 were written to disk byte-for-byte, so they
still carry whatever the camera put in them. Measured on prod that day: 38 of
55 files had an EXIF APP1 segment (device make and model, capture time to the
second) and 21 had a GPS IFD. Every one of those files is served publicly.

New uploads are cleaned by strip_metadata() in the upload handler; this fixes
the backlog. It rewrites files in place under their existing names, because
ratings.photo_url points at them -- renaming would break every stored URL.

    ./ops/strip-existing-exif.py                 # dry run, prod uploads
    ./ops/strip-existing-exif.py --apply
    ./ops/strip-existing-exif.py --dir /some/where --apply

Take a backup first (ops/backup.sh tars the uploads directory). Writes are
atomic -- a temp file in the same directory, then os.replace -- so an
interrupted run cannot leave a half-written photo where a valid one was.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from images import strip_metadata  # noqa: E402

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "uploads")
KNOWN_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# Substrings that mean metadata is present. Deliberately the same markers the
# verification used, so "clean" here means the same thing it did there.
MARKERS = (b"Exif\x00\x00", b"http://ns.adobe.com/xap", b"Photoshop 3.0")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR, help="uploads directory")
    ap.add_argument("--apply", action="store_true",
                    help="actually rewrite the files (default is a dry run)")
    args = ap.parse_args()

    updir = os.path.abspath(args.dir)
    if not os.path.isdir(updir):
        sys.exit(f"not a directory: {updir}")

    print(f"{'REWRITING' if args.apply else 'DRY RUN  '}  {updir}\n")

    changed = failed = skipped = 0
    saved = 0

    for name in sorted(os.listdir(updir)):
        path = os.path.join(updir, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in KNOWN_EXT:
            print(f"  skip     {name}  (unsupported extension)")
            skipped += 1
            continue

        raw = open(path, "rb").read()
        out = strip_metadata(raw, ext)

        if out == raw:
            # Either already clean, or unparseable and passed through. Say which.
            if any(m in raw for m in MARKERS):
                print(f"  FAILED   {name}  (metadata present but could not be stripped)")
                failed += 1
            else:
                skipped += 1
            continue

        leftover = [m for m in MARKERS if m in out]
        if leftover:
            print(f"  FAILED   {name}  (metadata survived: {leftover})")
            failed += 1
            continue

        delta = len(raw) - len(out)
        saved += delta
        changed += 1
        print(f"  {'strip   ' if args.apply else 'would   '} {name}  -{delta} bytes")

        if args.apply:
            tmp = path + ".stripping"
            with open(tmp, "wb") as f:
                f.write(out)
                f.flush()
                os.fsync(f.fileno())
            # Keep the original mode; a fresh temp file would be 0600 and nginx
            # serves these as a different user.
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
            os.replace(tmp, path)

    print(f"\n{changed} file(s) {'rewritten' if args.apply else 'would change'}, "
          f"{skipped} already clean or unsupported, {failed} failed, "
          f"{saved / 1024:.0f} KiB removed")
    if not args.apply and changed:
        print("\nRe-run with --apply to write. Back up first: ops/backup.sh")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
