#!/bin/sh

set -e

function moonraker_timelapse_message(){
  top_line
  title 'Moonraker Timelapse' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}Moonraker Timelapse is a 3rd party Moonraker component to    ${white}│"
  echo -e " │ ${cyan}create timelapse of 3D prints.                               ${white}│"
  hr
  bottom_line
}

function install_moonraker_timelapse(){
  moonraker_timelapse_message
  local yn
  while true; do
    install_msg "Moonraker Timelapse" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        if [ -f "$HS_CONFIG_FOLDER"/timelapse.cfg ]; then
          rm -f "$HS_CONFIG_FOLDER"/timelapse.cfg
        fi
        if [ ! -d "$HS_CONFIG_FOLDER" ]; then
          mkdir -p "$HS_CONFIG_FOLDER"
        fi
        echo -e "Info: Linking file..."
        ln -sf "$TIMELAPSE_URL1" "$TIMELAPSE_FILE"
        # The linked component is an untracked source file inside Moonraker's git
        # repo, so update_manager permanently reports the repo as dirty
        # ("Repo has untracked source files: ['moonraker/components/timelapse.py']").
        # Add it to the repo's local exclude list so update_manager stays happy.
        MOONRAKER_REPO_DIR="${TIMELAPSE_FILE%/moonraker/components/timelapse.py}"
        if [ -d "$MOONRAKER_REPO_DIR"/.git/info ]; then
          echo -e "Info: Excluding linked component from Moonraker repo..."
          grep -qxF "moonraker/components/timelapse.py" "$MOONRAKER_REPO_DIR"/.git/info/exclude 2>/dev/null \
            || echo "moonraker/components/timelapse.py" >> "$MOONRAKER_REPO_DIR"/.git/info/exclude
        fi
        if [ "$model" = "K1_2025" ]; then
          # K1_2025 runs Klipper as the unprivileged 'creality' user, which cannot read a
          # symlink whose target is in the root-owned helper-script tree (Klipper then reports
          # "Include file does not exist"). Use a real copy, and make the config dir
          # traversable (mkdir under root's umask creates it mode 700).
          chmod 755 "$HS_CONFIG_FOLDER"
          cp -f "$TIMELAPSE_URL2" "$HS_CONFIG_FOLDER"/timelapse.cfg
          chmod 644 "$HS_CONFIG_FOLDER"/timelapse.cfg
        else
          ln -sf "$TIMELAPSE_URL2" "$HS_CONFIG_FOLDER"/timelapse.cfg
        fi
        if grep -q "include Helper-Script/timelapse" "$PRINTER_CFG" ; then
          echo -e "Info: Moonraker Timelapse configurations are already enabled in printer.cfg file..."
        elif grep -q "\[include printer_params\.cfg\]" "$PRINTER_CFG" ; then
          echo -e "Info: Adding Moonraker Timelapse configurations in printer.cfg file..."
          sed -i '/\[include printer_params\.cfg\]/a \[include Helper-Script/timelapse\.cfg\]' "$PRINTER_CFG"
        else
          # K1_2025 ships a monolithic printer.cfg without the printer_params anchor;
          # prepend the include (owner-preserving rewrite so Klipper SAVE_CONFIG keeps working).
          echo -e "Info: Adding Moonraker Timelapse configurations in printer.cfg file..."
          { echo "[include Helper-Script/timelapse.cfg]"; cat "$PRINTER_CFG"; } > "$PRINTER_CFG.hs_tmp" && cat "$PRINTER_CFG.hs_tmp" > "$PRINTER_CFG" && rm -f "$PRINTER_CFG.hs_tmp"
        fi
        if grep -q "#\[timelapse\]" "$MOONRAKER_CFG" ; then
          echo -e "Info: Enabling Moonraker Timelapse configurations in moonraker.conf file..."
          sed -i -e 's/^\s*#[[:space:]]*\[timelapse\]/[timelapse]/' -e '/^\[timelapse\]/,/^\s*$/ s/^\(\s*\)#/\1/' "$MOONRAKER_CFG"
        else
          echo -e "Info: Moonraker Timelapse configurations are already enabled in moonraker.conf file..."
        fi
        echo -e "Info: Updating ffmpeg..."
        "$ENTWARE_FILE" update && "$ENTWARE_FILE" upgrade ffmpeg
        if [ "$model" = "K1_2025" ]; then
          # The timelapse component is loaded by Moonraker at startup, so Moonraker must be
          # restarted (not just Klipper) for it to register. S56moonraker_service has no
          # 'restart' verb, so stop + start. Run it in a subshell with umask 022: the
          # Creality root shell defaults to umask 077, and a Moonraker started that way writes
          # g-code uploads mode 600 — unreadable by the unprivileged 'creality' Klipper user,
          # so prints fail with XD5027 "Unable to open file".
          echo -e "Info: Restarting Moonraker service..."
          ( umask 022
            "$INITD_FOLDER"/S56moonraker_service stop 2>/dev/null
            sleep 1
            "$INITD_FOLDER"/S56moonraker_service start 2>/dev/null ) || true
        fi
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        ok_msg "Moonraker Timelapse has been installed successfully!"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_moonraker_timelapse(){
  moonraker_timelapse_message
  local yn
  while true; do
    remove_msg "Moonraker Timelapse" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Removing files..."
        rm -f "$HS_CONFIG_FOLDER"/timelapse.cfg
        rm -f /usr/data/moonraker/moonraker/moonraker/components/timelapse.py
        rm -f /usr/data/moonraker/moonraker/moonraker/components/timelapse.pyc
        # Drop the local exclude entry added at install time (symmetry).
        MOONRAKER_REPO_DIR="${TIMELAPSE_FILE%/moonraker/components/timelapse.py}"
        if [ -f "$MOONRAKER_REPO_DIR"/.git/info/exclude ]; then
          sed -i '/^moonraker\/components\/timelapse\.py$/d' "$MOONRAKER_REPO_DIR"/.git/info/exclude
        fi
        if [ -f /opt/bin/ffmpeg ]; then
          set +e
          "$ENTWARE_FILE" --autoremove remove ffmpeg
          set -e
        fi
        if grep -q "include Helper-Script/timelapse" "$PRINTER_CFG" ; then
          echo -e "Info: Removing Moonraker Timelapse configurations in printer.cfg file..."
          sed -i '/include Helper-Script\/timelapse\.cfg/d' "$PRINTER_CFG"
        else
          echo -e "Info: Moonraker Timelapse configurations are already removed in printer.cfg file..."
        fi
        if grep -q "\[timelapse\]" "$MOONRAKER_CFG" ; then
          echo -e "Info: Disabling Moonraker Timelapse configurations in moonraker.conf file..."
          sed -i '/^\[timelapse\]/,/^\s*$/ s/^\(\s*\)\([^#]\)/#\1\2/' "$MOONRAKER_CFG"
        else
          echo -e "Info: Moonraker Timelapse configurations are already disabled in moonraker.conf file..."
        fi
        if [ ! -n "$(ls -A "$HS_CONFIG_FOLDER")" ]; then
          rm -rf "$HS_CONFIG_FOLDER"
        fi
        echo -e "Info: Restarting Klipper service..."
        restart_klipper
        ok_msg "Moonraker Timelapse has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}