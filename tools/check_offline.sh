#!/usr/bin/env bash
# Prove the OCR pipeline needs no network: run it inside a network namespace
# that has no interfaces at all. If anything phoned home, this would fail.
#
#   sudo ./tools/check_offline.sh path/to/a-card.jpg
set -euo pipefail
cd "$(dirname "$0")/.."
IMG="${1:-}"
if [ -z "$IMG" ] || [ ! -f "$IMG" ]; then
  echo "usage: $0 <card-image>" >&2; exit 2
fi
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
unshare -n -- "$PY" -c "
import socket, sys
try:
    socket.create_connection(('1.1.1.1', 443), timeout=3)
    print('FAIL: namespace still has network; test is invalid'); sys.exit(1)
except OSError:
    pass
from app import ocr
r = ocr.read_card(open('$IMG','rb').read())
print('PASS: OCR completed with no network.')
print('  name  :', r['name'] or '(none found)')
print('  handle:', r['handle'] or '(none found)')
print('  links :', ', '.join(l['url'] for l in r['links']) or '(none found)')
"
