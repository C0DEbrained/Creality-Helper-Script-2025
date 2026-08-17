#!/bin/sh

set -e

function extended_gcode_params_message(){
  top_line
  title 'Extended Gcode Params' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}Klipper's extended g-code parser treats '#', ';' and '*' as  ${white}│"
  echo -e " │ ${cyan}comment characters even inside quotes, so a gcode file with  ${white}│"
  echo -e " │ ${cyan}one in its name cannot be printed from the web interface.    ${white}│"
  echo -e " │ ${cyan}This installs upstream's fixed parser (Klipper PR #6749).    ${white}│"
  hr
  bottom_line
}

function install_extended_gcode_params(){
  extended_gcode_params_message
  local yn
  while true; do
    install_msg "Extended Gcode Params" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Linking file..."
        ln -sf "$EXTENDED_GCODE_PARAMS_URL" "$KLIPPER_EXTRAS_FOLDER"/extended_gcode_params.py
        # Unlike Gcode Shell Command, this extra does nothing until a bare
        # [extended_gcode_params] section exists in printer.cfg — the module is
        # only loaded by klippy when its section is present.
        if grep -q "^\[extended_gcode_params\]" "$PRINTER_CFG" ; then
          echo -e "Info: Extended Gcode Params is already enabled in printer.cfg file..."
        else
          # Klipper owns everything below the SAVE_CONFIG marker and rewrites it,
          # so the section goes in above the marker on any printer that has ever
          # run SAVE_CONFIG, and at the end of the file on one that has not.
          echo -e "Info: Adding Extended Gcode Params configuration in printer.cfg file..."
          awk '!added && /^#\*#.*SAVE_CONFIG/ { if (prev != "") print ""; print "[extended_gcode_params]"; print ""; added=1 } { print; prev=$0 } END { if (!added) { if (prev != "") print ""; print "[extended_gcode_params]" } }' "$PRINTER_CFG" > "$PRINTER_CFG.hs_tmp" && cat "$PRINTER_CFG.hs_tmp" > "$PRINTER_CFG" && rm -f "$PRINTER_CFG.hs_tmp"
        fi
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        # The extra registers no status fields, so it never appears in the Klipper
        # API method "objects/list" — checking that list reports a working module as
        # missing. Klippy reaching "ready" with the section present is the load
        # proof, since an unfindable module is a config error rather than a ready
        # state. klippy.log also carries "upstream PR #6749 parser installed".
        ok_msg "Extended Gcode Params has been installed successfully!"
        echo -e " ${cyan}Gcode files with ${white}#${cyan}, ${white};${cyan} or ${white}*${cyan} in their name can now be printed.${white}"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_extended_gcode_params(){
  extended_gcode_params_message
  local yn
  while true; do
    remove_msg "Extended Gcode Params" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        # Remove the config section before the module, so klippy is never restarted
        # with a section it has no extra for.
        if grep -q "^\[extended_gcode_params\]" "$PRINTER_CFG" ; then
          echo -e "Info: Removing Extended Gcode Params configuration in printer.cfg file..."
          # Drops the blank line the installer put after the section too, so an
          # install/remove cycle on a printer that has run SAVE_CONFIG leaves
          # printer.cfg byte-identical rather than growing a blank line each time.
          awk '/^\[extended_gcode_params\]/ { skip=1; next } skip && /^$/ { skip=0; next } { skip=0; print }' "$PRINTER_CFG" > "$PRINTER_CFG.hs_tmp" && cat "$PRINTER_CFG.hs_tmp" > "$PRINTER_CFG" && rm -f "$PRINTER_CFG.hs_tmp"
        else
          echo -e "Info: Extended Gcode Params configurations are already removed in printer.cfg file..."
        fi
        echo -e "Info: Removing files..."
        rm -f "$KLIPPER_EXTRAS_FOLDER"/extended_gcode_params.py
        rm -f "$KLIPPER_EXTRAS_FOLDER"/extended_gcode_params.pyc
        rm -f "$KLIPPER_EXTRAS_FOLDER"/__pycache__/extended_gcode_params.*pyc 2>/dev/null || true
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        ok_msg "Extended Gcode Params has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
