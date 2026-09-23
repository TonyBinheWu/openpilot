#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd "$DIR" || exit 1
source "$DIR/launch_env.sh"

function boot_stage {
  echo "[hkg-boot] stage=$1 AGNOS_required=$AGNOS_VERSION"
  if [ -n "${HKG_BOOT_STAGE:-}" ]; then
    printf '%s\n' "$1" > "${HKG_BOOT_STAGE}.new"
    mv -f "${HKG_BOOT_STAGE}.new" "$HKG_BOOT_STAGE"
  fi
}

function boot_failure {
  echo "[hkg-boot] ERROR: $2 (exit=$1)" >&2
  exit "$1"
}

function agnos_init {
  boot_stage agnos-init
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta
  rm -f /data/scons_cache/config.lock

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Preserve sunnypilot's exact OS requirement and verification/flash implementation.
  local current_version
  current_version="$(cat /VERSION)" || boot_failure 42 "Cannot read /VERSION"
  echo "[hkg-boot] AGNOS_running=$current_version AGNOS_required=$AGNOS_VERSION"
  if [ "$current_version" != "$AGNOS_VERSION" ]; then
    AGNOS_PY="$DIR/openpilot/common/hardware/comma/agnos.py"
    MANIFEST="$DIR/openpilot/system/hardware/comma/agnos.json"
    local updater="$DIR/openpilot/common/hardware/comma/updater"
    boot_stage agnos-preflight
    [ -x "$AGNOS_PY" ] || boot_failure 42 "AGNOS script missing or not executable: $AGNOS_PY"
    [ -r "$MANIFEST" ] || boot_failure 42 "AGNOS manifest is not readable: $MANIFEST"
    python3 "$DIR/tools/boot/bootstrap.py" "$DIR" --check-updater "$updater"
    local rc=$?
    [ "$rc" -eq 0 ] || boot_failure "$rc" "AGNOS updater preflight failed"

    boot_stage agnos-verify
    if "$AGNOS_PY" --verify "$MANIFEST"; then
      boot_stage agnos-reboot
      sudo reboot || boot_failure 43 "Verified OS update but reboot failed"
      # Do not enter build on an old running OS while shutdown is pending.
      while true; do sleep 60; done
    fi

    boot_stage agnos-update
    "$updater" "$AGNOS_PY" "$MANIFEST"
    rc=$?
    echo "[hkg-boot] AGNOS_updater_exit=$rc"
    [ "$rc" -eq 0 ] || boot_failure "$rc" "AGNOS updater exited; not retrying a failed binary forever"

    # If the upstream updater returns, verify using the same upstream tool.
    # Never build against an unverified/mismatched OS, and never kill active flashing.
    boot_stage agnos-post-verify
    if "$AGNOS_PY" --verify "$MANIFEST"; then
      boot_stage agnos-reboot
      sudo reboot || boot_failure 43 "Verified OS update but reboot failed"
      while true; do sleep 60; done
    fi
    boot_failure 44 "AGNOS updater returned without a verified OS/reboot; required=$AGNOS_VERSION running=$current_version"
  fi
}

function launch {
  boot_stage launcher
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f "$DIR/.git/index.lock"

  # Apply only complete overlay updates, preserving the upstream mechanism.
  if [ -f "${DIR}/.overlay_init" ]; then
    find "${DIR}/.git" -newer "${DIR}/.overlay_init" | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv "$DIR" /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" "$DIR"
          cd "$DIR" || exit 1

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
        fi
      fi
    fi
  fi

  boot_stage package-setup
  ln -sfn "$PWD" /data/pythonpath
  export PYTHONPATH="$PWD"
  ln -sfn msgq_repo/msgq msgq
  ln -sfn opendbc_repo/opendbc opendbc
  ln -sfn rednose_repo/rednose rednose
  ln -sfn teleoprtc_repo/teleoprtc teleoprtc
  ln -sfn tinygrad_repo/tinygrad tinygrad

  if [ -f /AGNOS ]; then
    agnos_init
  fi

  tmux capture-pane -pq -S-1000 > /tmp/launch_log

  cd "$DIR/openpilot/system/manager" || boot_failure 45 "Manager directory missing"
  if [ ! -f "$DIR/prebuilt" ]; then
    boot_stage compilation
    ./build.py
    rc=$?
    [ "$rc" -eq 0 ] || boot_failure "$rc" "sunnypilot build failed; manager will not be started"
  fi
  boot_stage manager
  ./manager.py
  rc=$?
  [ "$rc" -eq 0 ] || boot_failure "$rc" "manager process exited with an error"
  boot_stage manager-exited
  while true; do sleep 60; done
}

launch
