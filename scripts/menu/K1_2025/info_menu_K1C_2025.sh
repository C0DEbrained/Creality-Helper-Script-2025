#!/bin/sh

set -e

function check_folder_k1_2025() {
  local folder_path="$1"
  if [ -d "$folder_path" ]; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

function check_file_k1_2025() {
  local file_path="$1"
  if [ -f "$file_path" ]; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

function check_any_file_k1_2025() {
  local file_path
  for file_path in "$@"; do
    if [ -f "$file_path" ]; then
      echo -e "${green}✓"
      return
    fi
  done
  echo -e "${red}✗"
}

function check_simplyprint_k1_2025() {
  if [ ! -f "$MOONRAKER_CFG" ]; then
    echo -e "${red}✗"
  elif grep -q "\[simplyprint\]" "$MOONRAKER_CFG"; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

# Tri-state: the camera gate makes a partial disable a normal outcome, so a plain
# tick would report a half-done state as finished. mDNS is opt-in and excluded.
function check_creality_services_k1_2025() {
  local svc any_disabled any_enabled
  any_disabled=""
  any_enabled=""
  for svc in $(creality_core_services); do
    if [ -f "$(creality_service_disabled_path "$svc")" ]; then
      any_disabled="1"
    elif [ -f "$svc" ]; then
      any_enabled="1"
    fi
  done
  if [ -z "$any_disabled" ]; then
    echo -e "${red}✗"
  elif [ -n "$any_enabled" ]; then
    echo -e "${yellow}~"
  else
    echo -e "${green}✓"
  fi
}

# Tri-state. `~` is not "half done" here, it is the state a firmware update
# leaves behind: the service file recreated beside the disabled copy, losing the
# race for port 7125 to Moonraker at every boot. Retire Nexusp Backend offers
# the repair.
function check_nexusp_retired_k1_2025() {
  if nexusp_absent; then
    # This firmware ships no nexusp in either form, so there is nothing to
    # retire. A red cross here would read as an unfinished action on a printer
    # where the action does not apply - the Customize menu already checks
    # nexusp_absent first for the same reason.
    echo -e "${cyan}-"
  elif nexusp_resurrected; then
    echo -e "${yellow}~"
  elif nexusp_retired; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

# The port Moonraker actually listens on, which is the whole point of retiring
# nexusp - and the one thing a user needs to know before pasting any command
# from a Klipper forum at this printer. Plain text, no colour escapes: info_line
# pads on ${#status} and a second escaped field would push the box out of shape.
function check_moonraker_port_k1_2025() {
  local port
  port="$(nexusp_moonraker_port)"
  if [ -z "$port" ]; then
    echo "port unknown"
  else
    echo "port $port"
  fi
}

function info_menu_ui_k1_2025() {
  top_line
  title '[ INFORMATION MENU ]' "${yellow}"
  inner_line
  hr
  subtitle '•ESSENTIALS:'
  info_line "$(check_folder_k1_2025 "$MOONRAKER_FOLDER")" 'Moonraker & Nginx'
  info_line "$(check_folder_k1_2025 "$FLUIDD_FOLDER")" 'Fluidd'
  info_line "$(check_folder_k1_2025 "$MAINSAIL_FOLDER")" 'Mainsail'
  hr
  subtitle '•UTILITIES:'
  info_line "$(check_file_k1_2025 "$ENTWARE_FILE")" 'Entware'
  info_line "$(check_file_k1_2025 "$KLIPPER_SHELL_FILE")" 'Klipper Gcode Shell Command'
  hr
  subtitle '•IMPROVEMENTS:'
  info_line "$(check_folder_k1_2025 "$KAMP_FOLDER")" 'Klipper Adaptive Meshing & Purging'
  info_line "$(check_file_k1_2025 "$BUZZER_FILE")" 'Buzzer Support'
  info_line "$(check_folder_k1_2025 "$NOZZLE_CLEANING_FOLDER")" 'Nozzle Cleaning Fan Control'
  info_line "$(check_file_k1_2025 "$FAN_CONTROLS_FILE")" 'Fans Control Macros'
  info_line "$(check_folder_k1_2025 "$IMP_SHAPERS_FOLDER")" 'Improved Shapers Calibrations'
  info_line "$(check_file_k1_2025 "$SHAPER_DEFS_FILE")" 'Restore Input Shapers'
  info_line "$(check_file_k1_2025 "$USEFUL_MACROS_FILE")" 'Useful Macros'
  info_line "$(check_file_k1_2025 "$SAVE_ZOFFSET_FILE")" 'Save Z-Offset Macros'
  info_line "$(check_file_k1_2025 "$SCREWS_ADJUST_FILE")" 'Screws Tilt Adjust Support'
  info_line "$(check_file_k1_2025 "$M600_SUPPORT_FILE")" 'M600 Support'
  info_line "$(check_file_k1_2025 "$GIT_BACKUP_FILE")" 'Git Backup'
  hr
  subtitle '•CAMERA:'
  info_line "$(check_file_k1_2025 "$TIMELAPSE_FILE")" 'Moonraker Timelapse'
  info_line "$(check_file_k1_2025 "$CAMERA_SETTINGS_FILE")" 'Camera Settings Control'
  info_line "$(check_any_file_k1_2025 "$USB_CAMERA_FILE" "$USB_CAMERA_LEGACY_FILE")" 'USB Camera Support'
  info_line "$(check_any_file_k1_2025 "$BUILTIN_CAMERA_FILE" "$BUILTIN_CAMERA_LEGACY_FILE")" 'Built-in Camera Fix'
  hr
  subtitle '•REMOTE ACCESS:'
  info_line "$(check_folder_k1_2025 "$OCTOEVERYWHERE_FOLDER")" 'OctoEverywhere'
  info_line "$(check_folder_k1_2025 "$MOONRAKER_OBICO_FOLDER")" 'Obico'
  info_line "$(check_folder_k1_2025 "$GUPPYFLO_FOLDER")" 'GuppyFLO'
  info_line "$(check_folder_k1_2025 "$MOBILERAKER_COMPANION_FOLDER")" 'Mobileraker Companion'
  info_line "$(check_folder_k1_2025 "$OCTOAPP_COMPANION_FOLDER")" 'OctoApp Companion'
  info_line "$(check_simplyprint_k1_2025)" 'SimplyPrint'
  hr
  subtitle '•CUSTOMIZATION:'
  info_line "$(check_file_k1_2025 "$FLUIDD_LOGO_FILE")" 'Creality Dynamic Logos for Fluidd'
  info_line "$(check_creality_services_k1_2025)" 'Creality Stock Services Disabled'
  info_line "$(check_nexusp_retired_k1_2025)" "Nexusp Backend Retired (Moonraker on $(check_moonraker_port_k1_2025))"
  hr
  inner_line
  hr
  bottom_menu_option 'b' 'Back to [Main Menu]' "${yellow}"
  bottom_menu_option 'q' 'Exit' "${darkred}"
  hr
  version_line "$(get_script_version)"
  bottom_line
}

function info_menu_k1_2025() {
  clear
  info_menu_ui_k1_2025
  local info_menu_opt
  while true; do
    read -p " ${white}Type your choice and validate with Enter: ${yellow}" info_menu_opt
    case "${info_menu_opt}" in
      B|b)
        clear; main_menu; break;;
      Q|q)
         clear; exit 0;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
  info_menu_k1_2025
}
