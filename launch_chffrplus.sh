#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
BOOT_DIAG="$DIR/tools/hkg_bootstrap.py"
BOOT_DIR="/data/hkg_boot"
mkdir -p "$BOOT_DIR" 2>/dev/null || BOOT_DIR="/tmp/hkg_boot"
mkdir -p "$BOOT_DIR" || exit 1

function boot_note {
  python3 "$BOOT_DIAG" --directory "$BOOT_DIR" mark "$@"
}

function boot_run {
  python3 "$BOOT_DIAG" --directory "$BOOT_DIR" run "$@"
}

function boot_fail {
  local stage="$1" rc="$2"
  boot_note "$stage" "Stopped, exit=$rc. Tap for log. Controls will not be restarted."
  # Do not depend on the application's TextWindow, Params or downloaded fonts.
  python3 "$BOOT_DIAG" --directory "$BOOT_DIR" screen >> "$BOOT_DIR/screen.log" 2>&1
  # A missing/broken display is logged; never continue to driving controls.
  exit 1
}

cd "$DIR" || exit 1
source "$DIR/launch_env.sh" || boot_fail "LAUNCH_ENV_FAILED" "$?"
python3 "$BOOT_DIAG" --directory "$BOOT_DIR" init "$DIR" "$AGNOS_VERSION" || exit 1

function agnos_init {
  boot_note "AGNOS_INIT" "Using sunnypilot version requirement: $AGNOS_VERSION"
  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta
  rm -f /data/scons_cache/config.lock

  # set success flag for current boot slot
  sudo abctl --set_success

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # Preserve sunnypilot's required OS, manifest, verifier and updater payload.
  local installed rc
  [ -r /VERSION ] || boot_fail "AGNOS_VERSION_UNREADABLE" 1
  installed="$(tr -d '\r\n' < /VERSION)"
  if [ "$installed" != "$AGNOS_VERSION" ]; then
    boot_note "AGNOS_VERSION_MISMATCH" "$installed -> $AGNOS_VERSION; update required, not bypassed"
    AGNOS_PY="$DIR/openpilot/common/hardware/comma/agnos.py"
    MANIFEST="$DIR/openpilot/system/hardware/comma/agnos.json"
    boot_run "AGNOS_UPDATER_INTEGRITY" python3 "$BOOT_DIAG" --directory "$BOOT_DIR" check-updater "$DIR"
    rc=$?
    [ "$rc" -eq 0 ] || boot_fail "AGNOS_UPDATER_INVALID" "$rc"

    boot_run "AGNOS_VERIFY" "$AGNOS_PY" --verify "$MANIFEST"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      boot_run "AGNOS_REBOOT" sudo reboot
      rc=$?
      [ "$rc" -eq 0 ] || boot_fail "AGNOS_REBOOT_FAILED" "$rc"
      sleep 10
      boot_fail "AGNOS_REBOOT_DID_NOT_COMPLETE" 1
    fi
    # A failed verification normally means the target slot still needs updating.
    # Do not kill an active updater or change partition/verification behavior.
    boot_run "AGNOS_UPDATE" "$DIR/openpilot/common/hardware/comma/updater" "$AGNOS_PY" "$MANIFEST"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      boot_fail "AGNOS_UPDATER_FAILED" "$rc"
    fi
    # The bundled UI can catch an exception and return 0 without updating.
    # Do not spin forever, or start new code on the old OS in that case.
    sleep 10
    boot_fail "AGNOS_UPDATER_RETURNED_WITHOUT_REBOOT" 1
  fi
  boot_note "AGNOS_VERSION_OK" "$installed matches sunnypilot requirement"
}

function launch {
  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f "$DIR/.git/index.lock"

  # Keep upstream overlay update handling; never reset the branch or re-clone.
  if [ -f "${DIR}/.overlay_init" ]; then
    find "${DIR}/.git" -newer "${DIR}/.overlay_init" | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"
          mv "$DIR" /data/safe_staging/old_openpilot || boot_fail "OVERLAY_BACKUP_FAILED" "$?"
          mv "${STAGING_ROOT}/finalized" "$DIR" || boot_fail "OVERLAY_INSTALL_FAILED" "$?"
          cd "$DIR" || boot_fail "OVERLAY_DIRECTORY_FAILED" "$?"
          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
        fi
      fi
    fi
  fi

  # Anchor paths to the checkout, not the caller's working directory.
  cd "$DIR" || boot_fail "CHECKOUT_DIRECTORY_FAILED" "$?"
  ln -sfn "$DIR" /data/pythonpath || boot_fail "PYTHONPATH_LINK_FAILED" "$?"
  export PYTHONPATH="$DIR"

  boot_note "PACKAGE_LINKS" "Checking initialized submodule packages"
  local pair target link
  for pair in msgq_repo/msgq:msgq opendbc_repo/opendbc:opendbc rednose_repo/rednose:rednose teleoprtc_repo/teleoprtc:teleoprtc tinygrad_repo/tinygrad:tinygrad; do
    target="${pair%:*}"
    link="${pair#*:}"
    [ -d "$DIR/$target" ] || boot_fail "SUBMODULE_MISSING_$link" 1
    ln -sfn "$target" "$link" || boot_fail "PACKAGE_LINK_FAILED_$link" "$?"
  done

  # Brief independent startup marker. Failure to render is not a boot failure.
  python3 "$BOOT_DIAG" --directory "$BOOT_DIR" screen --seconds 1 >> "$BOOT_DIR/screen.log" 2>&1 || true

  if [ -f /AGNOS ]; then
    agnos_init
  fi

  tmux capture-pane -pq -S-1000 > /tmp/launch_log 2>/dev/null || true
  cd "$DIR/openpilot/system/manager" || boot_fail "MANAGER_DIRECTORY_MISSING" "$?"
  if [ ! -f "$DIR/prebuilt" ]; then
    # Let this wrapper render build failures independently of the unbuilt UI.
    HKG_BOOTSTRAP_CAPTURE=1 boot_run "SUNNYPILOT_BUILD" ./build.py
    local rc=$?
    [ "$rc" -eq 0 ] || boot_fail "SUNNYPILOT_BUILD_FAILED" "$rc"
  fi

  # No diagnostic window/watchdog survives into manager or onroad operation.
  boot_note "MANAGER_HANDOFF" "Bootstrap complete; no diagnostic watchdog active"
  ./manager.py
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    tmux capture-pane -pq -S-120 > "$BOOT_DIR/manager-exit.log" 2>/dev/null || true
    boot_fail "MANAGER_EXITED" "$rc"
  fi
  boot_note "MANAGER_EXITED_CLEANLY" "Normal exit; no automatic relaunch"
  while true; do sleep 1; done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  launch
fi
