#!/bin/sh

set -e

# Firmware builds this restore is known-good on. A future Creality firmware could
# ship a different shaper_defs (or react differently to the change), so klippy is
# only modified on listed versions, matched as a substring of the reported firmware
# (check_fw_version, which returns /etc/version on the K1_2025). Space-separated;
# extend as builds are confirmed. Heads-up: .23 was never run on hardware, it is
# listed because its Klipper bytecode is identical to the verified .22. V1.1.0.27
# (the CFS-C build) is bytecode-identical to .26 and has one user execution report.
# Anyone on an unlisted build is stopped and asked to report it; klippy is touched
# only if they then answer "y" to proceeding anyway, and they are asked to report
# the outcome so the build can be listed.
RESTORE_SHAPERS_SUPPORTED_FW="V1.0.0.22.20250711S V1.0.0.23.20250722S V1.0.0.26.20251024S V1.1.0.27.20260424S"

# Input-shaper keys the restore can leave Creality's klippy unable to load.
# Creality's shaper_defs.pyc defines only 'ei' and input_shaper raises
# "Unsupported shaper type" for anything else, so once SHAPER_CALIBRATE +
# SAVE_CONFIG has written e.g. mzv, deleting shaper_defs.py alone (Remove, or a
# firmware update rewriting /usr/share) stops Klipper from starting.
RESTORE_SHAPERS_KEYS="shaper_type shaper_type_x shaper_type_y shaper_freq_x shaper_freq_y"

function restore_shapers_backup_file(){
  echo "$HS_BACKUP_FOLDER/restore-input-shapers/input_shaper.bak"
}

# Print "<where> <key> <value>" for every uncommented RESTORE_SHAPERS_KEYS line
# in [input_shaper], where <where> is "section" (the regular config) or
# "autosave" (the #*# SAVE_CONFIG block, which overrides the section).
function restore_shapers_read_cfg(){
  awk -v want="$RESTORE_SHAPERS_KEYS" '
    BEGIN { n = split(want, k, " "); for (i = 1; i <= n; i++) w[k[i]] = 1 }
    {
      line = $0; loc = "section"
      if (line ~ /^#\*#/) { loc = "autosave"; sub(/^#\*#[ \t]?/, "", line) }
      if (line ~ /^\[/) { sect[loc] = line; next }
      if (sect[loc] !~ /^\[input_shaper\]/) next
      if (line !~ /^[A-Za-z0-9_]+[ \t]*[:=]/) next
      key = line; sub(/[ \t]*[:=].*$/, "", key)
      if (!(key in w)) next
      val = line; sub(/^[^:=]*[:=][ \t]*/, "", val)
      sub(/[ \t]*[#;].*$/, "", val); sub(/[ \t]+$/, "", val)
      print loc, key, val
    }' "$1"
}

# The value Klipper uses for key $2 in a restore_shapers_read_cfg listing $1
# (autosave wins over section); empty if unset.
function restore_shapers_effective(){
  awk -v key="$2" '$2 == key { v[$1] = $3 } END { if ("autosave" in v) print v["autosave"]; else if ("section" in v) print v["section"] }' "$1"
}

# Where key $2 is set in listing $1: autosave, section, or empty.
function restore_shapers_where(){
  awk -v key="$2" '$2 == key { w[$1] = 1 } END { if ("autosave" in w) print "autosave"; else if ("section" in w) print "section" }' "$1"
}

# Edit key $3 inside [input_shaper] of printer.cfg in place ($2: section or
# autosave). With a value $4 the line is rewritten keeping its key and
# separator; without one the line is deleted. Other lines are untouched.
function restore_shapers_edit_cfg(){
  local cfg="$1" where="$2" key="$3" value="$4"
  awk -v where="$where" -v key="$key" -v value="$value" '
    {
      line = $0; loc = "section"; pre = ""
      if (line ~ /^#\*#/) { loc = "autosave"; match(line, /^#\*#[ \t]?/); pre = substr(line, 1, RLENGTH); line = substr(line, RLENGTH + 1) }
      if (line ~ /^\[/) sect[loc] = line
      else if (loc == where && sect[loc] ~ /^\[input_shaper\]/ && match(line, /^[A-Za-z0-9_]+[ \t]*[:=][ \t]*/)) {
        k = line; sub(/[ \t]*[:=].*$/, "", k)
        if (k == key) {
          if (value == "") next
          print pre substr(line, 1, RLENGTH) value
          next
        }
      }
      print $0
    }' "$cfg" > "$cfg.hs_tmp" && cat "$cfg.hs_tmp" > "$cfg" && rm -f "$cfg.hs_tmp"
}

# Drop a "#*# [input_shaper]" header that the restore left without options (the
# calibration created it on a printer.cfg that had none), with the "#*#" spacer
# line that follows it, so the file matches its pre-install state.
function restore_shapers_drop_empty_autosave(){
  local cfg="$1"
  awk '
    { l[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++) {
        if (l[i] ~ /^#\*#[ \t]*\[input_shaper\]/) {
          j = i + 1; opts = 0
          while (j <= NR && l[j] ~ /^#\*#/ && l[j] !~ /^#\*#[ \t]*\[/) { if (l[j] ~ /^#\*#[ \t]*[A-Za-z0-9_]/) opts = 1; j++ }
          if (!opts) { i = j - 1; continue }
        }
        print l[i]
      }
    }' "$cfg" > "$cfg.hs_tmp" && cat "$cfg.hs_tmp" > "$cfg" && rm -f "$cfg.hs_tmp"
}

# Record the current shaper settings before the first install, so Remove can put
# them back. An existing backup is kept: a reinstall (e.g. after a firmware
# update) would otherwise overwrite the pre-restore values with restored-model ones.
function restore_shapers_backup_cfg(){
  local bak
  bak="$(restore_shapers_backup_file)"
  if [ -f "$bak" ]; then
    echo -e "Info: Keeping the existing input-shaper settings backup..."
    return
  fi
  echo -e "Info: Backing up input-shaper settings from printer.cfg file..."
  mkdir -p "$(dirname "$bak")"
  restore_shapers_read_cfg "$PRINTER_CFG" > "$bak"
}

# Put printer.cfg back into a state Creality's ei-only klippy can load: restore
# the backed-up values where they are now set, never leave a key in both the
# section and the SAVE_CONFIG block, and set any remaining non-ei type to ei.
# Returns 2 when a type had to be forced to ei, so the caller asks for a
# recalibration (the frequency was fitted for the other model).
function restore_shapers_restore_cfg(){
  local bak cur key where old type recal=""
  bak="$(restore_shapers_backup_file)"
  cur="$PRINTER_CFG.hs_shapers"
  mkdir -p "$(dirname "$bak")"
  cp -f "$PRINTER_CFG" "$(dirname "$bak")/printer.cfg.before-remove" 2>/dev/null || true
  restore_shapers_read_cfg "$PRINTER_CFG" > "$cur"
  if [ -f "$bak" ]; then
    echo -e "Info: Restoring input-shaper settings from backup..."
    for key in $RESTORE_SHAPERS_KEYS ; do
      where="$(restore_shapers_where "$cur" "$key")"
      [ -n "$where" ] || continue
      old="$(restore_shapers_effective "$bak" "$key")"
      restore_shapers_edit_cfg "$PRINTER_CFG" "$where" "$key" "$old"
      if [ "$where" = "autosave" ] && [ -n "$(awk -v key="$key" '$1 == "section" && $2 == key' "$cur")" ]; then
        restore_shapers_edit_cfg "$PRINTER_CFG" section "$key" ""
      fi
    done
    restore_shapers_drop_empty_autosave "$PRINTER_CFG"
    restore_shapers_read_cfg "$PRINTER_CFG" > "$cur"
  fi
  for key in shaper_type shaper_type_x shaper_type_y ; do
    type="$(restore_shapers_effective "$cur" "$key")"
    if [ -n "$type" ] && [ "$type" != "ei" ]; then
      echo -e "Info: Setting ${key} from ${type} to ei (the only model Creality's Klipper supports)..."
      restore_shapers_edit_cfg "$PRINTER_CFG" "$(restore_shapers_where "$cur" "$key")" "$key" ei
      recal="1"
    fi
  done
  rm -f "$cur" "$bak"
  [ -z "$recal" ] || return 2
}

function restore_input_shapers_message(){
  top_line
  title 'Restore Input Shapers' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}The K1C 2025 firmware ships input-shaper calibration limited ${white}│"
  echo -e " │ ${cyan}to a single model (ei) and copies the Y-axis result onto X. ${white}│"
  echo -e " │ ${cyan}This restores the full Klipper shaper model set and          ${white}│"
  echo -e " │ ${cyan}independent per-axis calibration.                            ${white}│"
  hr
  bottom_line
}

function install_restore_input_shapers(){
  restore_input_shapers_message
  local yn
  while true; do
    install_msg "Restore Input Shapers" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        # Bail out on unverified firmware before touching klippy (see note at top).
        fw="$(check_fw_version)"
        verified=""
        for v in $RESTORE_SHAPERS_SUPPORTED_FW ; do
          if echo "$fw" | grep -qF "$v" ; then
            verified="1"
            break
          fi
        done
        if [ -z "$verified" ]; then
          error_msg "Restore Input Shapers is not verified for this firmware yet!"
          echo -e " ${cyan}Detected firmware: ${white}${fw:-unknown}${white}"
          echo -e " ${cyan}Verified firmware: ${white}${RESTORE_SHAPERS_SUPPORTED_FW}${white}"
          echo -e " ${cyan}Please report your version on Discord so it can be vetted and added:${white}"
          echo -e " ${cyan}https://discord.gg/BznpvBfrnw${white}"
          echo
          echo -e " ${yellow}You can install it anyway. This modifies Klipper on an untested build.${white}"
          echo -e " ${yellow}If Klipper fails to start afterwards, run Remove from this menu to undo it.${white}"
          echo -e " ${yellow}Either way, please report the result (works / fails) and your firmware${white}"
          echo -e " ${yellow}string above on Discord, so this build can be added to the verified list.${white}"
          local proceed
          read -r -p " ${white}Proceed anyway? (${yellow}y${white}/${yellow}N${white}): ${yellow}" proceed || proceed=""
          echo -e "${white}"
          case "${proceed}" in
            Y|y) echo -e "Info: Proceeding on unverified firmware ${fw:-unknown}...";;
            *)
              error_msg "Installation canceled!"
              return;;
          esac
        fi
        # 1. Restore the full shaper model set.
        # Creality's compiled shaper_defs.pyc trims INPUT_SHAPERS down to 'ei', so
        # SHAPER_CALIBRATE only ever fits ei. Dropping the stock shaper_defs.py beside it
        # makes Python load the source (a legacy .pyc next to source is ignored when the
        # .py is present), restoring zv/mzv/ei/2hump_ei/3hump_ei. shaper_calibrate.pyc
        # already knows every model; only the definitions list was stripped.
        restore_shapers_backup_cfg
        echo -e "Info: Restoring full input-shaper model set..."
        cp -f "$RESTORE_SHAPERS_URL" "$SHAPER_DEFS_FILE"
        chmod 644 "$SHAPER_DEFS_FILE"
        chown creality:creality "$SHAPER_DEFS_FILE" 2>/dev/null || true
        rm -f "$KLIPPER_EXTRAS_FOLDER"/__pycache__/shaper_defs.*pyc 2>/dev/null || true
        # 2. Calibrate X and Y independently (Creality copies Y->X by default via the
        # resonance_tester 'axis_x_use_y' option, which defaults to true).
        if grep -q "^[[:space:]]*axis_x_use_y" "$PRINTER_CFG" ; then
          echo -e "Info: Independent X/Y calibration is already enabled in printer.cfg file..."
        elif grep -q "^\[resonance_tester\]" "$PRINTER_CFG" ; then
          echo -e "Info: Enabling independent X/Y calibration in printer.cfg file..."
          awk '{print} /^\[resonance_tester\]/{print "axis_x_use_y: false"}' "$PRINTER_CFG" > "$PRINTER_CFG.hs_tmp" && cat "$PRINTER_CFG.hs_tmp" > "$PRINTER_CFG" && rm -f "$PRINTER_CFG.hs_tmp"
        else
          echo -e "${red}Warning: no [resonance_tester] section in printer.cfg; skipping axis_x_use_y.${white}"
        fi
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        ok_msg "Restore Input Shapers has been installed successfully!"
        echo -e " ${cyan}Run ${white}SHAPER_CALIBRATE${cyan} from the console, then ${white}SAVE_CONFIG${cyan} to apply.${white}"
        echo -e " ${yellow}After any Creality firmware update, reinstall Restore Input Shapers (or run${white}"
        echo -e " ${yellow}Remove to go back to ei) before printing: the update deletes the restored${white}"
        echo -e " ${yellow}models but printer.cfg keeps the calibrated type, and Klipper stops with${white}"
        echo -e " ${yellow}\"Unsupported shaper type\".${white}"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_restore_input_shapers(){
  restore_input_shapers_message
  local yn recal
  while true; do
    remove_msg "Restore Input Shapers" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Removing restored shaper definitions (Creality's shaper_defs.pyc takes over again)..."
        rm -f "$SHAPER_DEFS_FILE"
        rm -f "$KLIPPER_EXTRAS_FOLDER"/__pycache__/shaper_defs.*pyc 2>/dev/null || true
        recal=""
        restore_shapers_restore_cfg || recal="1"
        if grep -q "^[[:space:]]*axis_x_use_y" "$PRINTER_CFG" ; then
          echo -e "Info: Disabling independent X/Y calibration in printer.cfg file..."
          grep -v "^[[:space:]]*axis_x_use_y" "$PRINTER_CFG" > "$PRINTER_CFG.hs_tmp" && cat "$PRINTER_CFG.hs_tmp" > "$PRINTER_CFG" && rm -f "$PRINTER_CFG.hs_tmp"
        else
          echo -e "Info: Independent X/Y calibration is already disabled in printer.cfg file..."
        fi
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        ok_msg "Restore Input Shapers has been removed successfully!"
        if [ -n "$recal" ]; then
          echo -e " ${yellow}The input-shaper frequency in printer.cfg was fitted for another model.${white}"
          echo -e " ${yellow}Run ${white}SHAPER_CALIBRATE${yellow} from the console, then ${white}SAVE_CONFIG${yellow}, before printing.${white}"
        fi
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
