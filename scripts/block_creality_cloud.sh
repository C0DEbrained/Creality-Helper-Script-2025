#!/bin/sh

set -e

function block_creality_cloud_message(){
  top_line
  title 'Block Creality Cloud Telemetry' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}This allows to blackhole the Creality cloud hosts used by    ${white}│"
  echo -e " │ ${cyan}stock daemons for telemetry, remote access and OTA checks,   ${white}│"
  echo -e " │ ${cyan}and to drop outbound MQTT to anything outside your network.  ${white}│"
  hr
  echo -e " │ ${cyan}Remote access options (OctoEverywhere, Obico, GuppyFLO,      ${white}│"
  echo -e " │ ${cyan}SimplyPrint, OctoApp, Mobileraker) are not affected.         ${white}│"
  hr
  bottom_line
}

function install_block_creality_cloud(){
  block_creality_cloud_message
  local yn
  while true; do
    install_msg "Block Creality Cloud Telemetry" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Copying service file..."
        cp "$CLOUD_BLOCK_SERVICE_URL" "$CLOUD_BLOCK_SERVICE_FILE"
        chmod 755 "$CLOUD_BLOCK_SERVICE_FILE"
        echo -e "Info: Applying blocklist..."
        set +e
        "$CLOUD_BLOCK_SERVICE_FILE" start
        set -e
        ok_msg "Block Creality Cloud Telemetry has been installed successfully!"
        if ! command -v iptables > /dev/null 2>&1; then
          echo -e " ${darkred}Note: iptables is not available on this printer, MQTT port rules were skipped.${white}"
          echo -e " ${darkred}The hosts blocklist is still active.${white}"
          echo
        fi
        echo -e " ${white}Connections already open are not torn down, reboot to apply it fully.${white}"
        echo
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_block_creality_cloud(){
  block_creality_cloud_message
  local yn
  while true; do
    remove_msg "Block Creality Cloud Telemetry" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Restoring hosts file and removing rules..."
        set +e
        if [ -f "$CLOUD_BLOCK_SERVICE_FILE" ]; then
          "$CLOUD_BLOCK_SERVICE_FILE" stop
        fi
        set -e
        echo -e "Info: Removing file..."
        rm -f "$CLOUD_BLOCK_SERVICE_FILE"
        ok_msg "Block Creality Cloud Telemetry has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
