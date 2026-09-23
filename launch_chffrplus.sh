#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

BOOT_LOG="/tmp/tonypilot_boot.log"
BOOT_STAGE="/tmp/tonypilot_boot_stage"
BOOT_DIAG="$DIR/openpilot/system/manager/boot_diagnostics.py"
BOOT_WATCHDOG_PID=""

function boot_stage {
  local name="$1"
  local timeout_s="${2:-0}"
  printf '%s\n%s\n%s\n' "$name" "$(date +%s)" "$timeout_s" > "$BOOT_STAGE"
  echo "[tonypilot] stage: $name (timeout=${timeout_s}s)"
}

function boot_error {
  local code="${1:-1}"
  local where="${2:-unknown}"
  echo "[tonypilot] ERROR stage=$where exit=$code"
  boot_stage "error: $where" 0
  if [ -f "$BOOT_DIAG" ]; then
    python3 "$BOOT_DIAG" error "tonypilot startup error" "Stage: $where\nExit code: $code"
  fi
  while true; do sleep 60; done
}

function stop_boot_watchdog {
  boot_stage "complete" 0
  if [ -n "$BOOT_WATCHDOG_PID" ]; then
    kill "$BOOT_WATCHDOG_PID" 2>/dev/null || true
  fi
}

function agnos_init {
  boot_stage "AGNOS initialization" 1800
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta
  rm -f /data/scons_cache/config.lock

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Check if AGNOS update is required
  if [ "$(< /VERSION)" != "$AGNOS_VERSION" ]; then
    AGNOS_PY="$DIR/openpilot/common/hardware/comma/agnos.py"
    MANIFEST="$DIR/openpilot/system/hardware/comma/agnos.json"
    echo "[tonypilot] AGNOS mismatch: device=$(< /VERSION) required=$AGNOS_VERSION"
    boot_stage "AGNOS verify/update: device $(< /VERSION) -> $AGNOS_VERSION" 1800
    if "$AGNOS_PY" --verify "$MANIFEST"; then
      echo "[tonypilot] AGNOS target already verified, rebooting"
      sudo reboot
    fi

    local agnos_attempt=0
    while true; do
      agnos_attempt=$((agnos_attempt + 1))
      echo "[tonypilot] AGNOS updater attempt $agnos_attempt"
      "$DIR/openpilot/common/hardware/comma/updater" "$AGNOS_PY" "$MANIFEST"
      rc=$?
      echo "[tonypilot] AGNOS updater exit=$rc"
      if [ "$rc" -ne 0 ]; then
        sleep 5
      fi
    done
  fi
}

function launch {
  if [ -z "${TONYPILOT_BOOT_DIAG_ACTIVE:-}" ]; then
    export TONYPILOT_BOOT_DIAG_ACTIVE=1
    : > "$BOOT_LOG"
    exec > >(tee -a "$BOOT_LOG") 2>&1
  fi

  echo "[tonypilot] boot diagnostics enabled"
  echo "[tonypilot] branch=$(git -C "$DIR" branch --show-current 2>/dev/null || true)"
  echo "[tonypilot] commit=$(git -C "$DIR" rev-parse HEAD 2>/dev/null || true)"
  echo "[tonypilot] AGNOS=$(cat /VERSION 2>/dev/null || echo unknown), required=$AGNOS_VERSION"
  boot_stage "launcher initialization" 180

  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi

  # handle pythonpath
  ln -sfn $(pwd) /data/pythonpath
  export PYTHONPATH="$PWD"

  # submodule package symlinks for PYTHONPATH imports on device.
  # on PC these come from editable installs via pyproject.toml / uv.
  ln -sfn msgq_repo/msgq msgq
  ln -sfn opendbc_repo/opendbc opendbc
  ln -sfn rednose_repo/rednose rednose
  ln -sfn teleoprtc_repo/teleoprtc teleoprtc
  ln -sfn tinygrad_repo/tinygrad tinygrad

  # Start a visible watchdog after PYTHONPATH and package symlinks exist.
  if [ -f "$BOOT_DIAG" ]; then
    python3 "$BOOT_DIAG" watch "$BOOT_STAGE" >> "$BOOT_LOG" 2>&1 &
    BOOT_WATCHDOG_PID=$!
    echo "[tonypilot] watchdog pid=$BOOT_WATCHDOG_PID"
  fi

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
  fi

  boot_stage "startup log capture" 120

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  # start manager
  cd openpilot/system/manager
  if [ ! -f "$DIR/prebuilt" ]; then
    boot_stage "sunnypilot compilation" 1800
    ./build.py
    rc=$?
    if [ "$rc" -ne 0 ]; then
      boot_error "$rc" "sunnypilot compilation"
    fi
  fi

  boot_stage "manager startup" 240
  ./manager.py
  rc=$?
  boot_error "$rc" "manager exited unexpectedly"
}

launch
