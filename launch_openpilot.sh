#!/usr/bin/env bash

# Resolve the install root even if AGNOS starts the launcher from another cwd.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd "$DIR" || exit 1

# C4-only pre-build diagnostics. C3X keeps the direct upstream launcher path.
MODEL="$(tr -d '\000' < /sys/firmware/devicetree/base/model 2>/dev/null || true)"
if [ -f /AGNOS ] && [ "$MODEL" = "comma mici" ]; then
  source "$DIR/launch_env.sh"
  exec python3 "$DIR/tools/boot/bootstrap.py" "$DIR"
fi
exec ./launch_chffrplus.sh
