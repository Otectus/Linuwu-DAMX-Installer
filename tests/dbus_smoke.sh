#!/usr/bin/env bash
# Bridge from `dbus-run-session --` to the Python smoke harness. The
# `--` already isolates us in a private session bus, so we just need to
# invoke Python with the right paths.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/dbus_smoke.py"
