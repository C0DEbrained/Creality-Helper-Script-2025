#!/bin/sh

set -e

# The K1C 2025 runs TWO Moonrakers against one Klipper: Creality's forked
# `nexusp` on :7125 (the touchscreen's backend) and the helper script's real one
# on :7126. They share -d /usr/data/printer_data, so one gcode directory and one
# klippy socket, but Creality namespaced the databases.
#
# That split is not merely redundant, it is a trap, and the failure mode is the
# bad kind: querying the wrong port does not fail, it ANSWERS.
#
#   curl -s http://<printer>:7125/server/spoolman/status
#   # nexusp -> {"error": {"code": 404, "message": "Method not found"}}
#
# Read at face value that says Spoolman was never connected on this printer. It
# is wrong, and every user who pastes a :7125 command from a Klipper forum gets
# a plausible-looking wrong answer instead of an error.
#
# This option retires nexusp and puts the real Moonraker on :7125 - the port the
# entire Klipper ecosystem assumes. The touchscreen is never patched: `vectorp`
# hardcodes http://127.0.0.1:7125 and we own what answers there, which is the
# whole trick, because the binary CANNOT be patched - it is a symlink into tmpfs,
# regenerated at boot from an encrypted SCBT blob on p8.
#
# What is load-bearing is not the daemon, it is two JSON-RPC methods the screen
# calls that stock Moonraker does not have. files/moonraker/creality-compat/
# implements them; see the header of creality_compat.py.
#
# THE STEP ORDER IS NOT NEGOTIABLE, AND THE OBVIOUS ORDER IS WRONG
#
#   1  warn about anything that can restart Moonraker behind our back
#   2  stop Moonraker            -- both must be down before step 4
#   3  stop nexusp               --
#   4  merge the print history      (dry run, then --apply; backs up first)
#   5  install the compat component + uncomment [creality_compat]
#   6  rename CS56nexusp_service -> disabled.CS56nexusp_service  <- VERIFY
#   7  moonraker.conf: port 7126 -> 7125
#   8  nginx.conf: server 127.0.0.1:7126; -> :7125;
#   9  start Moonraker, reload nginx explicitly
#  10  verify :7125 answers
#
# "Merge the history first, before anything is disabled" is the obvious order
# and it is impossible: merge_job_history.py refuses to run while any Moonraker
# or nexusp process is alive, because Moonraker caches job_totals in memory and
# writes its stale copy back at the next print.
#
# Step 6 must be VERIFIED before step 7 runs. If the rename fails and the port
# has already moved, nexusp and the real Moonraker both want :7125 and the loser
# dies silently. This uses the same guarded-mv-with-rollback idiom as
# creality_disable_one_service in disable_creality_services.sh, but deliberately
# does NOT call that function: CREALITY_SERVICES_NEVER_DISABLE lists both
# S56nexusp_service and CS56nexusp_service, so it would refuse - correctly, since
# that option does not own nexusp and this one does.
#
# TWO TRAPS WORTH STATING HERE RATHER THAN LEARNING TWICE
#
# - Any Moonraker SUPERVISOR must be stopped first, not just the daemon. The
#   merge checks for a live daemon at one instant; a supervisor can restart
#   Moonraker in the gap and the restarted daemon flushes its cached job_totals
#   over the merged ones. This repo ships no watchdog, so upstream this is a
#   warning rather than a step - a fork that adds one owns disarming it.
# - nginx reload. files/services/S50nginx runs "$NGINX" -s reload with no -c on
#   its reload path, so nginx opens /etc/nginx/nginx.conf, which does not exist
#   on this board, fails, and leaves the OLD config live while reporting
#   nothing. That file is fixed in the same change as this one, but on boxes
#   where Creality's own S50nginx won the `[ ! -f ]` guard at install time the
#   shipped fix is not the file that runs - so reload explicitly here instead of
#   trusting the init verb.

NEXUSP_RETIRE_STAGE=0

function retire_nexusp_message(){
  top_line
  title 'Retire Nexusp Backend' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}The 2025 runs two Moonrakers against one Klipper: Creality's   ${white}│"
  echo -e " │ ${cyan}nexusp on port 7125 for the touchscreen, and the helper's on   ${white}│"
  echo -e " │ ${cyan}7126 for everything else. Querying the wrong one does not      ${white}│"
  echo -e " │ ${cyan}fail, it answers - wrongly. This retires nexusp, moves real    ${white}│"
  echo -e " │ ${cyan}Moonraker to 7125 and installs the two methods the screen      ${white}│"
  echo -e " │ ${cyan}needs. Your print history is merged, not replaced.             ${white}│"
  hr
  bottom_line
}

function restore_nexusp_message(){
  top_line
  title 'Restore Nexusp Backend' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}This puts Creality's nexusp back on port 7125 and returns the  ${white}│"
  echo -e " │ ${cyan}helper's Moonraker to 7126. Prints made while nexusp was       ${white}│"
  echo -e " │ ${cyan}retired are merged back into its database first, or the        ${white}│"
  echo -e " │ ${cyan}touchscreen's history would silently stop at the retire date.  ${white}│"
  hr
  bottom_line
}

# --------------------------------------------------------------------------
# Predicates. Pure: they read the filesystem and say what they see, and nothing
# here mutates anything - so the menus and the info screen can call them freely.
# --------------------------------------------------------------------------

function nexusp_disabled_path() {
  echo "$(dirname "$1")/disabled.$(basename "$1")"
}

# Both the S and CS prefixes: the init script name varies by firmware, and
# tools.sh and tools_menu_K1C_2025.sh already probe for both forms elsewhere.
function nexusp_service_files() {
  echo "$NEXUSP_SERVICE $NEXUSP_SERVICE_LEGACY"
}

# The enabled init script, if there is one. Empty otherwise.
#
# The trailing `return 0` is load-bearing: without it a loop that finds nothing
# returns the last failed `[ -f ]`, and `svc="$(nexusp_enabled_service)"` would
# then abort the whole helper under the `set -e` helper.sh applies globally.
# Absence is an answer here, not an error.
function nexusp_enabled_service() {
  local svc
  for svc in $(nexusp_service_files); do
    if [ -f "$svc" ]; then
      echo "$svc"
      return 0
    fi
  done
  return 0
}

# The disabled.* init script, if there is one. Empty otherwise.
function nexusp_disabled_service() {
  local svc disabled_svc
  for svc in $(nexusp_service_files); do
    disabled_svc="$(nexusp_disabled_path "$svc")"
    if [ -f "$disabled_svc" ]; then
      echo "$disabled_svc"
      return 0
    fi
  done
  return 0
}

function nexusp_present() {
  [ -n "$(nexusp_enabled_service)" ]
}

function nexusp_retired() {
  [ -n "$(nexusp_disabled_service)" ]
}

# True when this firmware ships no nexusp at all, in either form. Distinguishes
# "nothing to do here" from "already done", which look identical otherwise.
function nexusp_absent() {
  if nexusp_present || nexusp_retired; then
    return 1
  fi
  return 0
}

# BOTH forms present. /usr/apps/etc/init.d survives a factory reset, but a
# firmware OTA can put CS56nexusp_service back beside the disabled copy. When
# that happens /etc/init.d/rcK starts it from the CS pass while
# S56moonraker_service starts from the S pass, so the real Moonraker wins the
# :7125 bind and nexusp dies silently at every boot - both files present, the
# box in a state nobody diagnoses. Reported by the menus, repaired by re-running
# the rename.
function nexusp_resurrected() {
  if nexusp_present && nexusp_retired; then
    return 0
  fi
  return 1
}

# The port Moonraker is configured to listen on, or empty if unreadable. The
# pipe is deliberate: sed succeeds whether or not grep matched, so a config
# without a port line reads as "unknown" rather than aborting the helper.
function nexusp_moonraker_port() {
  if [ ! -f "$MOONRAKER_CFG" ]; then
    return 0
  fi
  grep -m 1 '^port:' "$MOONRAKER_CFG" 2>/dev/null | sed 's/^port:[[:space:]]*//'
}

# --------------------------------------------------------------------------
# Small helpers shared by both directions
# --------------------------------------------------------------------------

# The Moonraker virtualenv's interpreter when it exists, so the merge runs on
# the same Python the daemon does; plain python3 otherwise (a workstation
# rehearsal, or a box where Moonraker was installed some other way).
function nexusp_python() {
  if [ -x "$MOONRAKER_ENV_PYTHON" ]; then
    echo "$MOONRAKER_ENV_PYTHON"
  else
    echo "python3"
  fi
}

function nexusp_pillow_installed() {
  if [ ! -x "$MOONRAKER_ENV_PYTHON" ]; then
    return 1
  fi
  set +e
  "$MOONRAKER_ENV_PYTHON" -c "import PIL" > /dev/null 2>&1
  local rc=$?
  set -e
  return $rc
}

# The reload the init script's own verb cannot be trusted to do. See the header.
function nexusp_reload_nginx() {
  local conf
  echo -e "Info: Reloading Nginx..."
  set +e
  for conf in "$NGINX_CONF_FILE" /etc/nginx/nginx.conf; do
    if [ -f "$conf" ] && [ -x "$NGINX_BIN" ]; then
      "$NGINX_BIN" -c "$conf" -s reload > /dev/null 2>&1 && break
    fi
  done
  set -e
}

function nexusp_stop_service() {
  local svc
  svc="$(nexusp_enabled_service)"
  if [ -z "$svc" ]; then
    return
  fi
  echo -e "Info: Stopping nexusp..."
  set +e
  "$svc" stop > /dev/null 2>&1
  killall -q nexusp
  set -e
}

function nexusp_start_service() {
  local svc
  svc="$(nexusp_enabled_service)"
  if [ -z "$svc" ]; then
    return
  fi
  echo -e "Info: Starting nexusp..."
  set +e
  "$svc" start > /dev/null 2>&1
  set -e
}

# Moonraker's port and Nginx's upstream, as one operation, because they must
# always agree - a box where they disagree serves 502s from Fluidd and nothing
# says why. Also used by configure_moonraker_nginx_k1_2025 so a Moonraker
# reinstall cannot silently undo the swap.
function nexusp_set_moonraker_port() {
  local want="$1" other="$2" nginx_conf
  if [ -f "$MOONRAKER_CFG" ]; then
    echo -e "Info: Setting Moonraker port to ${want}..."
    sed -i "s/^port:[[:space:]]*${other}\$/port: ${want}/" "$MOONRAKER_CFG"
  fi
  for nginx_conf in "$NGINX_CONF_FILE" /etc/nginx/nginx.conf; do
    if [ -f "$nginx_conf" ]; then
      echo -e "Info: Pointing Nginx Moonraker upstream to port ${want}..."
      sed -i "s/server 127\.0\.0\.1:${other};/server 127.0.0.1:${want};/" "$nginx_conf"
    fi
  done
}

# Link the component in and enable it. Follows moonraker_timelapse.sh exactly:
# the linked file is an untracked source file inside Moonraker's git repo, so
# update_manager reports "Repo has untracked source files" forever unless it is
# added to the repo's local exclude list.
function nexusp_install_compat_component() {
  local repo_dir
  echo -e "Info: Linking Creality compatibility component..."
  ln -sf "$CREALITY_COMPAT_URL" "$CREALITY_COMPAT_FILE"
  repo_dir="${CREALITY_COMPAT_FILE%/moonraker/components/creality_compat.py}"
  if [ -d "$repo_dir"/.git/info ]; then
    echo -e "Info: Excluding linked component from Moonraker repo..."
    grep -qxF "moonraker/components/creality_compat.py" "$repo_dir"/.git/info/exclude 2>/dev/null \
      || echo "moonraker/components/creality_compat.py" >> "$repo_dir"/.git/info/exclude
  fi
  if [ ! -f "$MOONRAKER_CFG" ]; then
    return
  fi
  if grep -q "^\[creality_compat\]" "$MOONRAKER_CFG"; then
    echo -e "Info: [creality_compat] is already enabled in moonraker.conf file..."
  elif grep -q "^#\[creality_compat\]" "$MOONRAKER_CFG"; then
    echo -e "Info: Enabling [creality_compat] in moonraker.conf file..."
    sed -i -e 's/^\s*#[[:space:]]*\[creality_compat\]/[creality_compat]/' -e '/^\[creality_compat\]/,/^\s*$/ s/^\(\s*\)#/\1/' "$MOONRAKER_CFG"
  else
    # A moonraker.conf written before this option existed has no block to
    # uncomment. Without this branch the component would be linked and never
    # loaded, so the screen's file browser would stay broken with nothing to
    # show for it - and that is the majority case, since install_moonraker_nginx
    # only rewrites moonraker.conf when Moonraker itself is reinstalled.
    echo -e "Info: Adding [creality_compat] to moonraker.conf file..."
    printf '\n[creality_compat]\ngenerate_thumbnails: True\nlog_requests: False\n' >> "$MOONRAKER_CFG"
  fi
}

function nexusp_remove_compat_component() {
  local repo_dir
  echo -e "Info: Removing Creality compatibility component..."
  rm -f "$CREALITY_COMPAT_FILE"
  rm -f "${CREALITY_COMPAT_FILE}c"
  repo_dir="${CREALITY_COMPAT_FILE%/moonraker/components/creality_compat.py}"
  if [ -f "$repo_dir"/.git/info/exclude ]; then
    sed -i '/^moonraker\/components\/creality_compat\.py$/d' "$repo_dir"/.git/info/exclude
  fi
  if [ -f "$MOONRAKER_CFG" ] && grep -q "^\[creality_compat\]" "$MOONRAKER_CFG"; then
    echo -e "Info: Disabling [creality_compat] in moonraker.conf file..."
    sed -i '/^\[creality_compat\]/,/^\s*$/ s/^\(\s*\)\([^#]\)/#\1\2/' "$MOONRAKER_CFG"
  fi
}

# Everything install_moonraker_nginx would undo. It rm -f's moonraker.conf and
# re-copies the shipped one - which has [creality_compat] commented and port
# 7125 - then calls configure_moonraker_nginx_k1_2025, which used to sed the
# port back to 7126 unconditionally. On a retired box that left NOTHING
# answering :7125 and the touchscreen dead with no error anywhere.
function nexusp_reapply_retired_config() {
  nexusp_set_moonraker_port 7125 7126
  nexusp_install_compat_component
}

# The merge, in either direction, with the dry run shown first. Returns non-zero
# when it refuses; helper.sh sets -e globally and sources every script into the
# same shell, so an unguarded call would abort the whole helper and drop the
# user to a shell with no menu. Guarded at every call site.
function nexusp_merge_history() {
  local direction="$1" python
  python="$(nexusp_python)"
  if [ ! -f "$MOONRAKER_DB" ] || [ ! -f "$NEXUSP_DB" ]; then
    echo -e "Info: Only one print history database exists, nothing to merge..."
    return 0
  fi
  echo -e "Info: Print history merge (${direction}), dry run..."
  set +e
  "$python" "$MERGE_JOB_HISTORY_URL" --direction "$direction"
  local rc=$?
  if [ "$rc" != "0" ]; then
    set -e
    return "$rc"
  fi
  echo -e "Info: Merging print history..."
  "$python" "$MERGE_JOB_HISTORY_URL" --direction "$direction" --apply
  rc=$?
  set -e
  return "$rc"
}

# --------------------------------------------------------------------------
# Rollback. Undoes stages 6-8 in reverse, and is only ever called from the
# failure paths below - a partial swap is the one outcome worth more code than
# the swap itself, because the symptom is a dead touchscreen and nothing in any
# log to connect it to this option.
# --------------------------------------------------------------------------

function nexusp_rollback_retire() {
  local disabled_svc svc
  echo
  echo -e "${yellow}Rolling back...${white}"
  if [ "$NEXUSP_RETIRE_STAGE" -ge 8 ]; then
    nexusp_set_moonraker_port 7126 7125
  fi
  if [ "$NEXUSP_RETIRE_STAGE" -ge 6 ]; then
    disabled_svc="$(nexusp_disabled_service)"
    if [ -n "$disabled_svc" ]; then
      svc="$(dirname "$disabled_svc")/$(basename "$disabled_svc" | sed 's/^disabled\.//')"
      mv "$disabled_svc" "$svc" 2>/dev/null || true
    fi
  fi
  if [ "$NEXUSP_RETIRE_STAGE" -ge 5 ]; then
    nexusp_remove_compat_component
  fi
  nexusp_start_service
  start_moonraker
  nexusp_reload_nginx
  # The forward history merge is NOT undone, deliberately. Those rows are valid
  # Moonraker rows either way, and rolling them back would delete records that
  # exist in no other database - the exact loss this whole option is careful
  # about. Nothing else read them, so leaving them costs nothing.
  error_msg "Nexusp has NOT been retired - the printer is back as it was."
}

# --------------------------------------------------------------------------
# Repair after a firmware update put the service file back
# --------------------------------------------------------------------------

# Re-applies the rename, keeping the file the firmware just wrote. Offered from
# retire_nexusp because that is the option a user reaches for when the menus
# report the state, and it is the same rename either way. `mv -f` rather than a
# delete: the two files are the same firmware init script, and one move leaves
# exactly one copy instead of briefly leaving none.
function nexusp_repair_resurrection() {
  local svc disabled_svc
  svc="$(nexusp_enabled_service)"
  disabled_svc="$(nexusp_disabled_path "$svc")"
  if ! creality_confirm_printer_idle; then
    return
  fi
  nexusp_stop_service
  echo -e "Info: Re-applying the nexusp rename..."
  if ! mv -f "$svc" "$disabled_svc" 2>/dev/null; then
    error_msg "Could not rename $(basename "$svc") - is $(dirname "$svc") writable?"
    return
  fi
  if [ -f "$svc" ] || [ ! -f "$disabled_svc" ]; then
    error_msg "The nexusp service did not stay renamed!"
    return
  fi
  # The same update may also have reverted the port or the component.
  nexusp_reapply_retired_config
  echo -e "Info: Restarting Moonraker service..."
  stop_moonraker
  start_moonraker
  nexusp_reload_nginx
  ok_msg "The nexusp service has been disabled again!"
  echo -e "   ${cyan}Nothing else was changed; your history and settings are as they${white}"
  echo -e "   ${cyan}were before the firmware update.${white}"
}

# --------------------------------------------------------------------------
# Retire
# --------------------------------------------------------------------------

function retire_nexusp(){
  retire_nexusp_message
  echo
  echo -e " ${yellow}Warning: this changes which process answers the port the"
  echo -e " touchscreen depends on. Do it with the printer idle. The nexusp"
  echo -e " binary and its database are never deleted, so Restore Nexusp"
  echo -e " Backend puts everything back.${white}"
  echo
  local yn pillow_yn repair_yn svc disabled_svc answered
  NEXUSP_RETIRE_STAGE=0
  while true; do
    read -p "${white} Are you sure you want to retire ${green}Nexusp Backend ${white}? (${yellow}y${white}/${yellow}n${white}): ${yellow}" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        if [ ! -d "$MOONRAKER_FOLDER" ]; then
          error_msg "Moonraker is needed, please install it first!"
          return
        fi
        # A firmware update can put the service file back beside the disabled
        # copy. /etc/init.d/rcK then starts it from the CS pass while
        # S56moonraker_service starts from the S pass, so Moonraker wins the
        # :7125 bind and nexusp dies silently at every boot - both files
        # present, and nothing anywhere says why the touchscreen "randomly
        # stopped working after an update".
        if nexusp_resurrected; then
          echo -e " ${yellow}Both the nexusp service and its disabled copy exist. A firmware"
          echo -e " update recreated it, and it now loses the race for port 7125 to"
          echo -e " Moonraker at every boot. The repair is to re-apply the rename,"
          echo -e " keeping the file the update wrote.${white}"
          echo
          read -p " ${white}Disable the recreated ${green}nexusp service ${white}again? (${yellow}y${white}/${yellow}n${white}): ${yellow}" repair_yn
          echo -e "${white}"
          case "${repair_yn}" in
            Y|y)
              nexusp_repair_resurrection;;
            *)
              error_msg "Repair canceled!";;
          esac
          return
        fi
        if ! nexusp_present; then
          if nexusp_retired; then
            error_msg "Nexusp Backend is already retired!"
          else
            error_msg "No nexusp service was found on this firmware!"
          fi
          return
        fi
        if ! creality_confirm_printer_idle; then
          return
        fi

        # Every decision is collected BEFORE the first mutation, so an abandoned
        # prompt cannot leave the printer half-swapped.
        pillow_yn="n"
        if ! nexusp_pillow_installed; then
          echo -e " ${yellow}Pillow is not in Moonraker's virtualenv. Without it the screen"
          echo -e " shows no thumbnail at all for newly uploaded files - and that is"
          echo -e " true of Moonraker's own thumbnail parsing today, retired or not,"
          echo -e " so installing it fixes both. It is a large download and there may"
          echo -e " be no prebuilt wheel for this board.${white}"
          echo
          read -p " ${white}Install ${green}Pillow ${white}into Moonraker's virtualenv? (${yellow}y${white}/${yellow}n${white}): ${yellow}" pillow_yn
          echo -e "${white}"
        fi

        # Re-check immediately before mutating: the prompt above may have taken
        # a while, and a print may have been started from the screen.
        if ! creality_confirm_printer_idle; then
          return
        fi

        case "${pillow_yn}" in
          Y|y)
            echo -e "Info: Installing Pillow..."
            set +e
            "$MOONRAKER_ENV_PYTHON" -m pip install Pillow
            if [ "$?" != "0" ]; then
              echo -e "${yellow}Warning: Pillow could not be installed. Continuing without it -${white}"
              echo -e "${yellow}thumbnails already on disk are still listed.${white}"
            fi
            set -e;;
        esac

        NEXUSP_RETIRE_STAGE=1
        # 1. Anything that can restart Moonraker behind our back has to be off
        #    BEFORE the merge, not just the daemon. Nothing in this repo can, so
        #    this is a warning; a fork that ships a watchdog owns disarming it.
        echo -e "Info: If you run a Moonraker watchdog or supervisor, stop it now -"
        echo -e "      a restart mid-merge overwrites the merged totals."
        # 2-3. Both daemons down, or the merge refuses.
        echo -e "Info: Stopping Moonraker service..."
        stop_moonraker
        NEXUSP_RETIRE_STAGE=2
        nexusp_stop_service
        NEXUSP_RETIRE_STAGE=3

        # 4. The merge. Nothing has been renamed or re-pointed yet, so a refusal
        #    here just puts the daemons back.
        set +e
        nexusp_merge_history to-moonraker
        if [ "$?" != "0" ]; then
          set -e
          error_msg "The print history merge refused to run - nothing was changed."
          echo -e " ${darkred}See the message above. Retiring nexusp without it would leave${white}"
          echo -e " ${darkred}the screen with a history that starts on the day you installed${white}"
          echo -e " ${darkred}the helper script.${white}"
          nexusp_start_service
          start_moonraker
          return
        fi
        set -e
        NEXUSP_RETIRE_STAGE=4

        # 5. The component. Safe to install while nexusp is still enabled: it is
        #    inert until Moonraker loads it.
        nexusp_install_compat_component
        NEXUSP_RETIRE_STAGE=5

        # 6. The rename, guarded. An unguarded mv would abort the whole helper
        #    under set -e, leaving both daemons stopped with no message and no
        #    menu to return to.
        svc="$(nexusp_enabled_service)"
        disabled_svc="$(nexusp_disabled_path "$svc")"
        if [ -f "$disabled_svc" ]; then
          error_msg "Both $(basename "$svc") and $(basename "$disabled_svc") exist!"
          echo -e " ${darkred}A firmware update likely recreated it. Leaving both alone to${white}"
          echo -e " ${darkred}avoid losing the backup. Delete whichever copy you do not want${white}"
          echo -e " ${darkred}and run this option again.${white}"
          nexusp_rollback_retire
          return
        fi
        echo -e "Info: Disabling nexusp service..."
        if ! mv "$svc" "$disabled_svc" 2>/dev/null; then
          error_msg "Could not rename $(basename "$svc") - is $(dirname "$svc") writable?"
          nexusp_rollback_retire
          return
        fi
        # VERIFIED, not assumed. If the rename silently did not take and the
        # port moves anyway, both daemons want :7125 and the loser dies with
        # nothing in any log.
        if [ -f "$svc" ] || [ ! -f "$disabled_svc" ]; then
          error_msg "The nexusp service did not stay renamed!"
          nexusp_rollback_retire
          return
        fi
        NEXUSP_RETIRE_STAGE=6

        # 7-8. The port, on both sides at once.
        nexusp_set_moonraker_port 7125 7126
        NEXUSP_RETIRE_STAGE=8

        # 9. Start, and reload nginx explicitly rather than trusting the verb.
        echo -e "Info: Starting Moonraker service..."
        start_moonraker
        nexusp_reload_nginx
        NEXUSP_RETIRE_STAGE=9

        # 10. Verify something actually answers on the port the screen polls.
        set +e
        "$CURL" -s -m 5 http://127.0.0.1:7125/server/info | grep -q '"result"'
        answered=$?
        set -e
        if [ "$answered" != "0" ]; then
          error_msg "Nothing answered on port 7125 after the swap!"
          nexusp_rollback_retire
          return
        fi

        ok_msg "Nexusp Backend has been retired successfully!"
        echo -e "   ${cyan}Moonraker now answers on 7125 for the touchscreen and for you.${white}"
        echo -e "   ${cyan}The touchscreen reconnects on its own; give it a few seconds.${white}"
        echo -e "   ${cyan}For about four seconds after a COLD boot the screen polls two${white}"
        echo -e "   ${cyan}methods Moonraker only registers once Klipper connects. It${white}"
        echo -e "   ${cyan}resolves itself and needs no action.${white}"
        echo -e "   ${cyan}A firmware update can put the nexusp service back - the menus${white}"
        echo -e "   ${cyan}report it, and re-running this option repairs it.${white}"
        return;;
      N|n)
        error_msg "Retiring canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------

function restore_nexusp(){
  restore_nexusp_message
  echo
  echo -e " ${yellow}Warning: while nexusp was retired the touchscreen wrote its"
  echo -e " history to Moonraker's database. Those prints are merged back into"
  echo -e " nexusp's before it starts, so this takes longer than it sounds -"
  echo -e " skipping it would make every print since the swap disappear from"
  echo -e " the screen with no warning.${white}"
  echo
  local yn svc disabled_svc
  while true; do
    restore_msg "Nexusp Backend" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        if ! nexusp_retired; then
          error_msg "Nexusp Backend is not retired!"
          return
        fi
        if ! creality_confirm_printer_idle; then
          return
        fi

        echo -e "Info: If you run a Moonraker watchdog or supervisor, stop it now -"
        echo -e "      a restart mid-merge overwrites the merged totals."
        echo -e "Info: Stopping Moonraker service..."
        stop_moonraker

        # The merge, BACKWARDS, while both are stopped. This must NOT try to
        # un-merge the forward direction: those rows are valid Moonraker rows
        # either way and rolling them back would delete records that have no
        # other copy.
        set +e
        nexusp_merge_history to-nexusp
        if [ "$?" != "0" ]; then
          set -e
          error_msg "The print history merge refused to run - nothing was changed."
          echo -e " ${darkred}See the message above. Restoring without it would hand the${white}"
          echo -e " ${darkred}screen a history frozen at the day you retired nexusp.${white}"
          start_moonraker
          return
        fi
        set -e

        # Reverse of 8, then 7, then 6.
        nexusp_set_moonraker_port 7126 7125
        nexusp_remove_compat_component
        disabled_svc="$(nexusp_disabled_service)"
        svc="$(dirname "$disabled_svc")/$(basename "$disabled_svc" | sed 's/^disabled\.//')"
        if [ -f "$svc" ]; then
          echo -e "${yellow}Warning: $(basename "$svc") already exists - the firmware recreated it.${white}"
          echo -e "${yellow}Keeping the newer file; $(basename "$disabled_svc") left in place.${white}"
        else
          echo -e "Info: Restoring nexusp service..."
          if ! mv "$disabled_svc" "$svc" 2>/dev/null; then
            error_msg "Could not restore $(basename "$svc") - is $(dirname "$svc") writable?"
            start_moonraker
            return
          fi
        fi

        echo -e "Info: Starting Moonraker service..."
        start_moonraker
        nexusp_start_service
        nexusp_reload_nginx
        ok_msg "Nexusp Backend has been restored successfully!"
        echo -e "   ${cyan}The touchscreen is back on nexusp, and Moonraker on 7126.${white}"
        return;;
      N|n)
        error_msg "Restoration canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
