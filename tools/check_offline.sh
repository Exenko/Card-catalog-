#!/usr/bin/env bash
# Prove the whole image pipeline needs no network: run auto-crop AND OCR inside
# a network namespace that has no interfaces at all. If any part of it phoned
# home, this would fail.
#
#   sudo ./tools/check_offline.sh path/to/a-card-photo.jpg
set -euo pipefail
cd "$(dirname "$0")/.."
IMG="${1:-}"
if [ -z "$IMG" ] || [ ! -f "$IMG" ]; then
  echo "usage: $0 <card-photo>" >&2; exit 2
fi
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
unshare -n -- "$PY" -c "
import socket, sys
try:
    socket.create_connection(('1.1.1.1', 443), timeout=3)
    print('FAIL: namespace still has network; test is invalid'); sys.exit(1)
except OSError:
    pass

from app import images, ocr
raw = open('$IMG','rb').read()
img, cropped = images.prepare(raw, auto_crop=True)
if img is None:
    print('FAIL: could not read that image'); sys.exit(1)
r = ocr.read_card(images.encode_jpeg(img))
print('PASS: auto-crop and OCR both completed with no network.')
print('  auto-cropped :', 'yes, to %dx%d' % img.size if cropped else 'no card outline found, kept whole')
print('  name         :', r['name'] or '(none found)')
print('  handle       :', r['handle'] or '(none found)')
print('  links        :', ', '.join(l['url'] for l in r['links']) or '(none found)')
"
