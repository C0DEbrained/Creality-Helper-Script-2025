#!/bin/sh

set -e

# The K1C 2025 starts its stock daemons from /usr/apps/etc/init.d via /etc/init.d/rcK,
# which iterates over "$(ls -r .../CS??*)". That glob still matches a ".disabled"
# SUFFIX, so the suffix rename used for the /usr/bin binaries in
# creality_web_interface.sh would be a silent no-op here - the daemon would simply
# start again at the next boot. Every rename below therefore uses the "disabled."
# PREFIX, matching what moonraker_nginx.sh already does for S56moonraker_service and
# what tools_menu_K1C_2025.sh checks for the Klipper configuration lock.
#
# Services this option must never disable, whatever a later edit is tempted to add:
#   klipper_service - Klipper itself.
#   nexusp_service  - the touchscreen backend on :7125; the GUI holds an open
#                     connection to it.
#   quintusp        - HAL for the LCD backlight, chassis LED, camera arbitration
#                     and the power-loss GPIO. Disabling it breaks power-loss
#                     recovery, and it can cancel a running print.
#   gui_service     - vectorp, the touchscreen itself.
# Both the S and CS prefixes are listed because the init script names vary by
# firmware - tools.sh and tools_menu_K1C_2025.sh already probe for both forms.
CREALITY_SERVICES_NEVER_DISABLE="S55klipper_service CS55klipper_service S56nexusp_service CS56nexusp_service S59quintusp CS59quintusp S60gui_service CS60gui_service"

function disable_creality_services_message(){
  top_line
  title 'Disable Creality Stock Services' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}Creality's stock firmware runs background daemons that upload  ${white}│"
  echo -e " │ ${cyan}configuration and logs to Creality, plus WebRTC daemons that   ${white}│"
  echo -e " │ ${cyan}go inert once the Built-in Camera Fix takes the camera.        ${white}│"
  echo -e " │ ${cyan}This disables the non-essential ones. It can be undone.        ${white}│"
  hr
  bottom_line
}

function restore_creality_services_message(){
  top_line
  title 'Restore Creality Stock Services' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}This re-enables the Creality stock services turned off by the  ${white}│"
  echo -e " │ ${cyan}Disable Creality Stock Services option.                        ${white}│"
  hr
  bottom_line
}

function creality_service_disabled_path() {
  echo "$(dirname "$1")/disabled.$(basename "$1")"
}

# The always-attempted set. mDNS is deliberately excluded: it is opt-in, so
# leaving it enabled is the expected outcome and must not read as "not finished".
function creality_core_services() {
  echo "$CREALITY_TELEMETRY_SERVICE $CREALITY_CLOUD_WEBRTC_SERVICE $CREALITY_LOCAL_WEBRTC_SERVICE $CREALITY_AI_SERVICE"
}

# Every service this option is allowed to touch, in rename order.
function creality_stock_services() {
  echo "$(creality_core_services) $CREALITY_MDNS_SERVICE"
}

function creality_services_pending() {
  local svc
  for svc in $(creality_stock_services); do
    if [ -f "$svc" ]; then
      return 0
    fi
  done
  return 1
}

function creality_services_disabled_present() {
  local svc
  for svc in $(creality_stock_services); do
    if [ -f "$(creality_service_disabled_path "$svc")" ]; then
      return 0
    fi
  done
  return 1
}

# True only when none of the five names exist in either form - i.e. this firmware
# does not ship the daemons this option knows about. Distinguishes "already done"
# from "nothing here to do", which look identical from creality_services_pending.
function creality_services_absent() {
  if creality_services_pending || creality_services_disabled_present; then
    return 1
  fi
  return 0
}

# Only the Built-in Camera Fix takes /dev/video0 - files/services/S50builtin_camera-k1c-2025
# runs mjpg_streamer against it. USB Camera Support deliberately EXCLUDES the built-in
# device (files/services/S50usb_camera-k1c-2025 filters out $BUILTIN_DEV), so a USB-only
# install leaves /dev/video0 free and onyxp/thirteenthp/solusp still serve the Creality
# app camera. Gating on either fix would silently remove a working feature.
function creality_builtin_camera_fix_installed() {
  if [ ! -f "$BUILTIN_CAMERA_FILE" ] && [ ! -f "$BUILTIN_CAMERA_LEGACY_FILE" ]; then
    return 1
  fi
  return 0
}

# 0 = printing or paused, 1 = confirmed idle, 2 = could not be determined.
# Both ports are consulted and any "printing" wins: helper Moonraker moves to 7126 on
# this model (moonraker_nginx.sh), while nexusp answers on 7125 whether or not Moonraker
# is installed. Only an explicitly known idle state counts as idle - anything else falls
# through to 2 so the caller asks the user rather than assuming the printer is free.
# jq is not available on the K1_2025 path, so the state is pulled out with sed/grep, and
# the body is trimmed to the print_stats object first so an unrelated "state" key in
# nexusp's response cannot be mistaken for the print state.
function creality_print_in_progress() {
  local port body state seen_idle
  seen_idle=""
  for port in 7126 7125; do
    body="$("$CURL" -s -m 3 "http://127.0.0.1:${port}/printer/objects/query?print_stats" 2>/dev/null)"
    case "$body" in
      *'"print_stats"'*)
        ;;
      *)
        continue;;
    esac
    state="$(echo "$body" | sed 's/.*"print_stats"//' | grep -o '"state"[[:space:]]*:[[:space:]]*"[A-Za-z_]*"' | head -n 1 | sed 's/.*"\([A-Za-z_]*\)"$/\1/')"
    case "$state" in
      printing|paused)
        return 0;;
      standby|complete|completed|cancelled|canceled|error)
        seen_idle="1";;
      *)
        ;;
    esac
  done
  if [ -n "$seen_idle" ]; then
    return 1
  fi
  return 2
}

# Set by creality_disable_one_service / creality_restore_one_service so the caller can
# report what actually happened instead of asserting success.
CREALITY_SERVICES_CHANGED=0
CREALITY_SERVICES_FAILED=0
CREALITY_SERVICES_STILL_RUNNING=""

function creality_disable_one_service() {
  local svc="$1"
  local proc="$2"
  local label="$3"
  local disabled_svc never

  # Enforced, not just documented: adding one of these to a tier above cannot
  # disable it by accident.
  for never in $CREALITY_SERVICES_NEVER_DISABLE; do
    if [ "$(basename "$svc")" = "$never" ]; then
      error_msg "$never is required by the printer and will not be disabled!"
      CREALITY_SERVICES_FAILED=$((CREALITY_SERVICES_FAILED + 1))
      return
    fi
  done

  disabled_svc="$(creality_service_disabled_path "$svc")"
  if [ ! -f "$svc" ]; then
    if [ -f "$disabled_svc" ]; then
      echo -e "Info: $label is already disabled, skipping..."
    else
      echo -e "Info: $label is not present on this firmware, skipping..."
    fi
    return
  fi
  if [ -f "$disabled_svc" ]; then
    echo -e "${yellow}Warning: both $(basename "$svc") and $(basename "$disabled_svc") exist.${white}"
    echo -e "${yellow}The firmware likely recreated it. Leaving it alone to avoid losing the backup.${white}"
    CREALITY_SERVICES_FAILED=$((CREALITY_SERVICES_FAILED + 1))
    return
  fi

  echo -e "Info: Stopping and disabling $label..."
  set +e
  "$svc" stop > /dev/null 2>&1
  if [ -n "$proc" ]; then
    killall -q "$proc"
  fi
  set -e
  # Guarded: an unguarded mv would abort the whole helper under set -e (helper.sh
  # sets it globally and functions.sh run() calls the action as a bare $1), leaving
  # the daemon stopped but not renamed with no message and no menu to return to.
  if ! mv "$svc" "$disabled_svc" 2>/dev/null; then
    error_msg "Could not rename $(basename "$svc") - is $(dirname "$svc") writable?"
    set +e
    "$svc" start > /dev/null 2>&1
    set -e
    CREALITY_SERVICES_FAILED=$((CREALITY_SERVICES_FAILED + 1))
    return
  fi
  CREALITY_SERVICES_CHANGED=$((CREALITY_SERVICES_CHANGED + 1))
  if [ -n "$proc" ]; then
    set +e
    pidof "$proc" > /dev/null 2>&1
    if [ "$?" = "0" ]; then
      CREALITY_SERVICES_STILL_RUNNING="$CREALITY_SERVICES_STILL_RUNNING $proc"
    fi
    set -e
  fi
}

function creality_restore_one_service() {
  local svc="$1"
  local label="$2"
  local disabled_svc

  disabled_svc="$(creality_service_disabled_path "$svc")"
  if [ ! -f "$disabled_svc" ]; then
    echo -e "Info: $label is not disabled, skipping..."
    return
  fi
  if [ -f "$svc" ]; then
    echo -e "${yellow}Warning: $(basename "$svc") already exists - the firmware recreated it.${white}"
    echo -e "${yellow}Keeping the newer file; $(basename "$disabled_svc") left in place.${white}"
    CREALITY_SERVICES_FAILED=$((CREALITY_SERVICES_FAILED + 1))
    return
  fi
  echo -e "Info: Restoring and starting $label..."
  if ! mv "$disabled_svc" "$svc" 2>/dev/null; then
    error_msg "Could not restore $(basename "$svc") - is $(dirname "$svc") writable?"
    CREALITY_SERVICES_FAILED=$((CREALITY_SERVICES_FAILED + 1))
    return
  fi
  CREALITY_SERVICES_CHANGED=$((CREALITY_SERVICES_CHANGED + 1))
  set +e
  "$svc" start > /dev/null 2>&1
  set -e
}

# Shared by both flows. 0 = safe to continue, 1 = caller should return.
function creality_confirm_printer_idle() {
  local print_state confirm
  set +e
  creality_print_in_progress
  print_state=$?
  set -e
  if [ "$print_state" -eq 0 ]; then
    error_msg "A print is in progress, please wait until it is finished!"
    return 1
  fi
  if [ "$print_state" -eq 2 ]; then
    echo -e " ${yellow}Warning: printer state could not be read on port 7126 or 7125.${white}"
    echo
    read -p " ${white}Confirm that no print is running (${yellow}y${white}/${yellow}n${white}): ${yellow}" confirm
    echo -e "${white}"
    case "${confirm}" in
      Y|y)
        return 0;;
      *)
        error_msg "Operation canceled!"
        return 1;;
    esac
  fi
  return 0
}

function disable_creality_services(){
  disable_creality_services_message
  echo
  echo -e " ${yellow}Warning: these services live on a partition that survives a factory"
  echo -e " reset, so a reset will not bring them back. Use Restore Creality Stock"
  echo -e " Services to undo this.${white}"
  echo
  local yn mdns_yn camera_fix
  while true; do
    disable_msg "Creality Stock Services" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        if ! creality_confirm_printer_idle; then
          return
        fi

        # Every decision is collected BEFORE the first rename, so an abandoned
        # prompt cannot leave the printer half-disabled, and the idle check below
        # cannot go stale while the user reads a question.
        camera_fix="no"
        if creality_builtin_camera_fix_installed; then
          camera_fix="yes"
        else
          echo -e "${yellow}Warning: the Built-in Camera Fix is not installed, so onyxp, thirteenthp${white}"
          echo -e "${yellow}and solusp are left running - they still serve the Creality app camera,${white}"
          echo -e "${yellow}local WebRTC and AI detection while /dev/video0 is free.${white}"
          echo -e "${yellow}(USB Camera Support does not take the built-in camera, so it does not${white}"
          echo -e "${yellow}count here.)${white}"
          echo
        fi
        mdns_yn="n"
        if [ -f "$CREALITY_MDNS_SERVICE" ]; then
          echo -e " ${yellow}Disabling mDNS also stops <hostname>.local resolution and Creality"
          echo -e " Print / app discovery on the local network.${white}"
          echo
          read -p " ${white}Also disable ${green}mDNS advertising ${white}? (${yellow}y${white}/${yellow}n${white}): ${yellow}" mdns_yn
          echo -e "${white}"
        fi

        # Re-check immediately before mutating: the prompts above may have taken a while.
        if ! creality_confirm_printer_idle; then
          return
        fi

        CREALITY_SERVICES_CHANGED=0
        CREALITY_SERVICES_FAILED=0
        CREALITY_SERVICES_STILL_RUNNING=""
        creality_disable_one_service "$CREALITY_TELEMETRY_SERVICE" "alchemistp" "Creality telemetry agent (alchemistp)"
        if [ "$camera_fix" = "yes" ]; then
          creality_disable_one_service "$CREALITY_CLOUD_WEBRTC_SERVICE" "onyxp" "Creality cloud WebRTC signalling (onyxp)"
          creality_disable_one_service "$CREALITY_LOCAL_WEBRTC_SERVICE" "thirteenthp" "Creality local WebRTC media server (thirteenthp)"
          creality_disable_one_service "$CREALITY_AI_SERVICE" "solusp" "Creality AI failure detection (solusp)"
        fi
        case "${mdns_yn}" in
          Y|y)
            creality_disable_one_service "$CREALITY_MDNS_SERVICE" "mdns" "Creality mDNS advertising (mdns)";;
          *)
            if [ -f "$CREALITY_MDNS_SERVICE" ]; then
              echo -e "Info: Leaving mDNS advertising enabled..."
            fi;;
        esac

        if [ "$CREALITY_SERVICES_CHANGED" -eq 0 ]; then
          error_msg "No Creality stock services were disabled!"
          if [ "$CREALITY_SERVICES_FAILED" -gt 0 ]; then
            echo -e " ${darkred}$CREALITY_SERVICES_FAILED service(s) could not be disabled - see the messages above.${white}"
          else
            echo -e " ${darkred}None of the expected service files were found on this firmware.${white}"
          fi
          echo
          return
        fi
        ok_msg "$CREALITY_SERVICES_CHANGED Creality stock service(s) have been disabled successfully!"
        if [ "$CREALITY_SERVICES_FAILED" -gt 0 ]; then
          echo -e "   ${yellow}$CREALITY_SERVICES_FAILED service(s) were skipped - see the messages above.${white}"
        fi
        if [ -n "$CREALITY_SERVICES_STILL_RUNNING" ]; then
          echo -e "   ${yellow}Still running:$CREALITY_SERVICES_STILL_RUNNING - please reboot to stop them.${white}"
        else
          echo -e "   ${cyan}The services were stopped, so no reboot is needed.${white}"
        fi
        echo -e "   ${cyan}The change persists across reboots and factory resets until restored.${white}"
        return;;
      N|n)
        error_msg "Disabling canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function restore_creality_services(){
  restore_creality_services_message
  local yn
  while true; do
    restore_msg "Creality Stock Services" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        # Restoring restarts onyxp/thirteenthp/solusp, which compete for /dev/video0
        # with the Built-in Camera Fix, so this path needs the same idle check as disable.
        if ! creality_confirm_printer_idle; then
          return
        fi
        if creality_builtin_camera_fix_installed; then
          echo -e "${yellow}Warning: the Built-in Camera Fix is installed. Restoring these services${white}"
          echo -e "${yellow}puts them back in contention for the camera - restart the camera or${white}"
          echo -e "${yellow}reboot if the stream misbehaves afterwards.${white}"
          echo
        fi
        CREALITY_SERVICES_CHANGED=0
        CREALITY_SERVICES_FAILED=0
        creality_restore_one_service "$CREALITY_TELEMETRY_SERVICE" "Creality telemetry agent (alchemistp)"
        creality_restore_one_service "$CREALITY_CLOUD_WEBRTC_SERVICE" "Creality cloud WebRTC signalling (onyxp)"
        creality_restore_one_service "$CREALITY_LOCAL_WEBRTC_SERVICE" "Creality local WebRTC media server (thirteenthp)"
        creality_restore_one_service "$CREALITY_AI_SERVICE" "Creality AI failure detection (solusp)"
        creality_restore_one_service "$CREALITY_MDNS_SERVICE" "Creality mDNS advertising (mdns)"
        if [ "$CREALITY_SERVICES_CHANGED" -eq 0 ]; then
          error_msg "No Creality stock services were restored!"
          echo
          return
        fi
        ok_msg "$CREALITY_SERVICES_CHANGED Creality stock service(s) have been restored successfully!"
        if [ "$CREALITY_SERVICES_FAILED" -gt 0 ]; then
          echo -e "   ${yellow}$CREALITY_SERVICES_FAILED service(s) were skipped - see the messages above.${white}"
        fi
        return;;
      N|n)
        error_msg "Restoration canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
