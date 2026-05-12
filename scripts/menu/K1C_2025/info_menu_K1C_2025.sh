#!/bin/sh

set -e

function check_folder_k1c_2025() {
  local folder_path="$1"
  if [ -d "$folder_path" ]; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

function check_file_k1c_2025() {
  local file_path="$1"
  if [ -f "$file_path" ]; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

function check_simplyprint_k1c_2025() {
  if [ ! -f "$MOONRAKER_CFG" ]; then
    echo -e "${red}✗"
  elif grep -q "\[simplyprint\]" "$MOONRAKER_CFG"; then
    echo -e "${green}✓"
  else
    echo -e "${red}✗"
  fi
}

function info_menu_ui_k1c_2025() {
  top_line
  title '[ INFORMATION MENU ]' "${yellow}"
  inner_line
  hr
  subtitle '•ESSENTIALS:'
  info_line "$(check_folder_k1c_2025 "$MOONRAKER_FOLDER")" 'Moonraker & Nginx'
  info_line "$(check_folder_k1c_2025 "$FLUIDD_FOLDER")" 'Fluidd'
  info_line "$(check_folder_k1c_2025 "$MAINSAIL_FOLDER")" 'Mainsail'
  hr
  subtitle '•UTILITIES:'
  info_line "$(check_file_k1c_2025 "$ENTWARE_FILE")" 'Entware'
  info_line "$(check_file_k1c_2025 "$KLIPPER_SHELL_FILE")" 'Klipper Gcode Shell Command'
  hr
  subtitle '•IMPROVEMENTS:'
  info_line "$(check_folder_k1c_2025 "$KAMP_FOLDER")" 'Klipper Adaptive Meshing & Purging'
  info_line "$(check_file_k1c_2025 "$BUZZER_FILE")" 'Buzzer Support'
  info_line "$(check_folder_k1c_2025 "$NOZZLE_CLEANING_FOLDER")" 'Nozzle Cleaning Fan Control'
  info_line "$(check_file_k1c_2025 "$FAN_CONTROLS_FILE")" 'Fans Control Macros' 
  info_line "$(check_folder_k1c_2025 "$IMP_SHAPERS_FOLDER")" 'Improved Shapers Calibrations'
  info_line "$(check_file_k1c_2025 "$USEFUL_MACROS_FILE")" 'Useful Macros'
  info_line "$(check_file_k1c_2025 "$SAVE_ZOFFSET_FILE")" 'Save Z-Offset Macros'
  info_line "$(check_file_k1c_2025 "$SCREWS_ADJUST_FILE")" 'Screws Tilt Adjust Support'
  info_line "$(check_file_k1c_2025 "$M600_SUPPORT_FILE")" 'M600 Support'
  info_line "$(check_file_k1c_2025 "$GIT_BACKUP_FILE")" 'Git Backup'
  hr
  subtitle '•CAMERA:'
  info_line "$(check_file_k1c_2025 "$TIMELAPSE_FILE")" 'Moonraker Timelapse'
  info_line "$(check_file_k1c_2025 "$CAMERA_SETTINGS_FILE")" 'Camera Settings Control'
  info_line "$(check_file_k1c_2025 "$USB_CAMERA_FILE")" 'USB Camera Support'
  info_line "$(check_file_k1c_2025 "$BUILTIN_CAMERA_FILE")" 'Built-in Camera Fix'
  hr
  subtitle '•REMOTE ACCESS:'
  info_line "$(check_folder_k1c_2025 "$OCTOEVERYWHERE_FOLDER")" 'OctoEverywhere'
  info_line "$(check_folder_k1c_2025 "$MOONRAKER_OBICO_FOLDER")" 'Obico'
  info_line "$(check_folder_k1c_2025 "$GUPPYFLO_FOLDER")" 'GuppyFLO'
  info_line "$(check_folder_k1c_2025 "$MOBILERAKER_COMPANION_FOLDER")" 'Mobileraker Companion'
  info_line "$(check_folder_k1c_2025 "$OCTOAPP_COMPANION_FOLDER")" 'OctoApp Companion'
  info_line "$(check_simplyprint_k1c_2025)" 'SimplyPrint'
  hr
  subtitle '•CUSTOMIZATION:'
  info_line "$(check_file_k1c_2025 "$FLUIDD_LOGO_FILE")" 'Creality Dynamic Logos for Fluidd'
  hr
  inner_line
  hr
  bottom_menu_option 'b' 'Back to [Main Menu]' "${yellow}"
  bottom_menu_option 'q' 'Exit' "${darkred}"
  hr
  version_line "$(get_script_version)"
  bottom_line
}

function info_menu_k1c_2025() {
  clear
  info_menu_ui_k1c_2025
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
  info_menu_k1c_2025
}
