#!/usr/bin/env bash
# Local development server, data in ./data. Needs tesseract-ocr on the host.
set -euo pipefail
cd "$(dirname "$0")"
export CARDCATALOG_DATA="${CARDCATALOG_DATA:-$PWD/data}"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
