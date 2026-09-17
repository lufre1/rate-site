#!/bin/bash
# Regenerate frontend/public/qr.png from a URL using qrcode in docker
# Usage: ./make-qr.sh [url]
# Default: https://c100-246.cloud.gwdg.de

set -e

# Get repo root from script location
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="${1:-https://c100-246.cloud.gwdg.de}"

docker run --rm -v "$REPO_ROOT":/repo -w /repo python:3.11 sh -c \
  'pip install --quiet qrcode[pil] && python -c "import qrcode; qrcode.make(\"$1\").save(\"frontend/public/qr.png\")"' \
  -- "$URL"

echo "QR code generated for: $URL"