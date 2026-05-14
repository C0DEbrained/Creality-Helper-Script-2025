#!/bin/sh

set -e

function remove_menu_ui_k1c_2025() {
  top_line
  title '[ REMOVE MENU ]' "${yellow}"
  inner_line
  hr
  subtitle '•ESSENTIALS:'
  menu_option ' 1' 'Remove' 'Moonraker and Nginx'
  menu_option ' 2' 'Remove' 'Fluidd (port 4408)'
  menu_option ' 3' 'Remove' 'Mainsail (port 4409)'
  menu_option ' 4' 'Remove' 'Reccon'
  hr
  subtitle '•UTILITIES:'
  menu_option ' 5' 'Remove' 'Entware'
  menu_option ' 6' 'Remove' 'Klipper Gcode Shell Command'
  hr
  subtitle '•CAMERA:'
  menu_option ' 7' 'Remove' 'Go2rtc'
  menu_option ' 8' 'Remove' 'USB Camera Support'
  menu_option ' 9' 'Remove' 'Built-in Camera Fix'
  menu_option '10' 'Remove' 'Camera Settings Control'
#  hr
#  subtitle '•IMPROVEMENTS:'
#  disabled_menu_option ' 6' 'Remove' 'Klipper Adaptive Meshing & Purging'
#  disabled_menu_option ' 7' 'Remove' 'Buzzer Support'
#  disabled_menu_option ' 8' 'Remove' 'Nozzle Cleaning Fan Control'
#  disabled_menu_option ' 9' 'Remove' 'Fans Control Macros'
#  disabled_menu_option '10' 'Remove' 'Improved Shapers Calibrations'
#  disabled_menu_option '11' 'Remove' 'Useful Macros'
#  disabled_menu_option '12' 'Remove' 'Save Z-Offset Macros'
#  disabled_menu_option '13' 'Remove' 'Screws Tilt Adjust Support'
#  disabled_menu_option '14' 'Remove' 'M600 Support'
#  disabled_menu_option '15' 'Remove' 'Git Backup'
#  hr
#  subtitle '•CAMERA:'
#  disabled_menu_option '16' 'Remove' 'Moonraker Timelapse'
#  disabled_menu_option '17' 'Remove' 'Camera Settings Control'
#  disabled_menu_option '18' 'Remove' 'USB Camera Support'
#  hr
#  subtitle '•REMOTE ACCESS:'
#  disabled_menu_option '19' 'Remove' 'OctoEverywhere'
#  disabled_menu_option '20' 'Remove' 'Moonraker Obico'
#  disabled_menu_option '21' 'Remove' 'GuppyFLO'
#  disabled_menu_option '22' 'Remove' 'Mobileraker Companion'
#  disabled_menu_option '23' 'Remove' 'OctoApp Companion'
#  disabled_menu_option '24' 'Remove' 'SimplyPrint'
  hr
  inner_line
  hr
  bottom_menu_option 'b' 'Back to [Main Menu]' "${yellow}"
  bottom_menu_option 'q' 'Exit' "${darkred}"
  hr
  version_line "$(get_script_version)"
  bottom_line
}

function remove_menu_k1c_2025() {
  clear
  remove_menu_ui_k1c_2025
  local remove_menu_opt
  while true; do
    read -p " ${white}Type your choice and validate with Enter: ${yellow}" remove_menu_opt
    case "${remove_menu_opt}" in
      1)
        if [ ! -d "$MOONRAKER_FOLDER" ] && [ ! -d "$NGINX_FOLDER" ]; then
          error_msg "Moonraker and Nginx are not installed!"
        elif [ -d "$GUPPY_SCREEN_FOLDER" ]; then
          error_msg "Moonraker is needed to use Guppy Screen, please uninstall it first!"
        else
         run "remove_moonraker_nginx" "remove_menu_ui_k1c_2025"
        fi;;
      2)
        if [ ! -d "$FLUIDD_FOLDER" ]; then
          error_msg "Fluidd is not installed!"
        elif [ ! -f "$CREALITY_WEB_FILE" ] && [ ! -d "$MAINSAIL_FOLDER" ]; then
          error_msg "Creality Web Interface is removed!"
          echo -e " ${darkred}Please restore Creality Web Interface first if you want to remove Fluidd.${white}"
          echo
        else
          run "remove_fluidd" "remove_menu_ui_k1c_2025"
        fi;;
      3)
        if [ ! -d "$MAINSAIL_FOLDER" ]; then
          error_msg "Mainsail is not installed!"
        elif [ ! -f "$CREALITY_WEB_FILE" ] && [ ! -d "$FLUIDD_FOLDER" ]; then
          error_msg "Creality Web Interface is removed!"
          echo -e " ${darkred}Please restore Creality Web Interface first if you want to remove Mainsail.${white}"
          echo
        else
          run "remove_mainsail" "remove_menu_ui_k1c_2025"
        fi;;
      4)
        if [ ! -f "$RECCON_FILE" ] && [ ! -f "$RECCON_SERVICE_FILE" ]; then
          error_msg "Reccon is not installed!"
        else
          run "remove_reccon" "remove_menu_ui_k1c_2025"
        fi;;
      5)
        if [ ! -f "$ENTWARE_FILE" ]; then
          error_msg "Entware is not installed!"
        elif [ -f "$TIMELAPSE_FILE" ]; then
          error_msg "Entware is needed to use Moonraker Timelapse, please uninstall it first!"
        elif [ -f "$GIT_BACKUP_FILE" ]; then
          error_msg "Entware is needed to use Git Backup, please uninstall it first!"
        elif [ -d "$OCTOEVERYWHERE_FOLDER" ]; then
          error_msg "Entware is needed to use OctoEverywhere, please uninstall it first!"
        elif [ -d "$MOONRAKER_OBICO_FOLDER" ]; then
          error_msg "Entware is needed to use Moonraker Obico, please uninstall it first!"
        elif [ -f "$USB_CAMERA_FILE" ] || [ -f "$USB_CAMERA_LEGACY_FILE" ]; then
          error_msg "Entware is needed to use USB Camera Support, please uninstall it first!"
        elif [ -f "$BUILTIN_CAMERA_FILE" ] || [ -f "$BUILTIN_CAMERA_LEGACY_FILE" ]; then
          error_msg "Entware is needed to use Built-in Camera Fix, please uninstall it first!"
        else
          run "remove_entware" "remove_menu_ui_k1c_2025"
        fi;;
      6)
        if [ ! -f "$KLIPPER_SHELL_FILE" ]; then
          error_msg "Klipper Gcode Shell Command is not installed!"
        elif [ -f "$BUZZER_FILE" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Buzzer Support, please uninstall it first!"
        elif [ -f "$CAMERA_SETTINGS_FILE" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Camera Settings Control, please uninstall it first!"
        elif [ -d "$GUPPY_SCREEN_FOLDER" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Guppy Screen, please uninstall it first!"
        elif [ -d "$IMP_SHAPERS_FOLDER" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Improved Shapers Calibrations, please uninstall it first!"
        elif [ -f "$GIT_BACKUP_FILE" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Git Backup, please uninstall it first!"
        elif [ -f "$USEFUL_MACROS_FILE" ]; then
          error_msg "Klipper Gcode Shell Command is needed to use Useful Macros, please uninstall it first!"
        else
          run "remove_gcode_shell_command" "remove_menu_ui_k1c_2025"
        fi;;

      7)
        if [ ! -f "$GO2RTC_FILE" ]; then
          error_msg "Go2rtc is not installed!"
        else
          run "remove_go2rtc" "remove_menu_ui_k1c_2025"
        fi;;
      8)
        if [ ! -f "$USB_CAMERA_FILE" ] && [ ! -f "$USB_CAMERA_LEGACY_FILE" ]; then
          error_msg "USB Camera Support is not installed!"
        else
          run "remove_usb_camera" "remove_menu_ui_k1c_2025"
        fi;;
      9)
        if [ ! -f "$BUILTIN_CAMERA_FILE" ] && [ ! -f "$BUILTIN_CAMERA_LEGACY_FILE" ]; then
          error_msg "Built-in Camera Fix is not installed!"
        else
          run "remove_builtin_camera" "remove_menu_ui_k1c_2025"
        fi;;
      10)
        if [ ! -f "$CAMERA_SETTINGS_FILE" ]; then
          error_msg "Camera Settings Control is not installed!"
        else
          run "remove_camera_settings_control" "remove_menu_ui_k1c_2025"
        fi;;

#      6)
#        disabled_feature;;
#        if [ ! -d "$KAMP_FOLDER" ]; then
#          error_msg "Klipper Adaptive Meshing & Purging is not installed!"
#        else
#          run "remove_kamp" "remove_menu_ui_k1c_2025"
#        fi;;
#      7)
#        disabled_feature;;
##        if [ ! -f "$BUZZER_FILE" ]; then
##          error_msg "Buzzer Support is not installed!"
##        else
##          run "remove_buzzer_support" "remove_menu_ui_k1c_2025"
##        fi;;
#      8)
#        disabled_feature;;
##        if [ ! -d "$NOZZLE_CLEANING_FOLDER" ]; then
##          error_msg "Nozzle Cleaning Fan Control is not installed!"
##        else
##          run "remove_nozzle_cleaning_fan_control" "remove_menu_ui_k1c_2025"
##        fi;;
#      9)
#        disabled_feature;;
##        if [ ! -f "$FAN_CONTROLS_FILE" ]; then
##          error_msg "Fans Control Macros are not installed!"
##        else
##          run "remove_fans_control_macros" "remove_menu_ui_k1c_2025"
##        fi;;
#      10)
#        disabled_feature;;
##        if [ ! -d "$IMP_SHAPERS_FOLDER" ]; then
##          error_msg "Improved Shapers Calibrations are not installed!"
##        else
##          run "remove_improved_shapers" "remove_menu_ui_k1c_2025"
##        fi;;
#      11)
#        disabled_feature;;
##        if [ ! -f "$USEFUL_MACROS_FILE" ]; then
##          error_msg "Useful Macros are not installed!"
##        else
##          run "remove_useful_macros" "remove_menu_ui_k1c_2025"
##        fi;;
#      12)
#        disabled_feature;;
##        if [ ! -f "$SAVE_ZOFFSET_FILE" ]; then
##          error_msg "Save Z-Offset Macros are not installed!"
##        else
##          run "remove_save_zoffset_macros" "remove_menu_ui_k1c_2025"
##        fi;;
#      13)
#        disabled_feature;;
##        if [ ! -f "$SCREWS_ADJUST_FILE" ]; then
##          error_msg "Screws Tilt Adjust Support is not installed!"
##        else
##          run "remove_screws_tilt_adjust" "remove_menu_ui_k1c_2025"
##        fi;;
#      14)
#        disabled_feature;;
##        if [ ! -f "$M600_SUPPORT_FILE" ]; then
##          error_msg "M600 Support is not installed!"
##        else
##          run "remove_m600_support" "remove_menu_ui_k1c_2025"
##        fi;;
#      15)
#        disabled_feature;;
##        if [ ! -f "$GIT_BACKUP_FILE" ]; then
##          error_msg "Git Backup is not installed!"
##        else
##          run "remove_git_backup" "remove_menu_ui_k1c_2025"
##        fi;;
#      16)
#        disabled_feature;;
##        if [ ! -f "$TIMELAPSE_FILE" ]; then
##          error_msg "Moonraker Timelapse is not installed!"
##        else
##          run "remove_moonraker_timelapse" "remove_menu_ui_k1c_2025"
##        fi;;
#      17)
#        disabled_feature;;
##        if [ ! -f "$CAMERA_SETTINGS_FILE" ]; then
##          error_msg "Camera Settings Control is not installed!"
##        else
##          run "remove_camera_settings_control" "remove_menu_ui_k1c_2025"
##        fi;;
#      18)
#        disabled_feature;;
##        if [ ! -f "$USB_CAMERA_FILE" ]; then
##          error_msg "USB Camera Support is not installed!"
##        else
##          run "remove_usb_camera" "remove_menu_ui_k1c_2025"
##        fi;;
#      19)
#        disabled_feature;;
##        if [ ! -d "$OCTOEVERYWHERE_FOLDER" ]; then
##          error_msg "OctoEverywhere is not installed!"
##        else
##          run "remove_octoeverywhere" "remove_menu_ui_k1c_2025"
##        fi;;
#      20)
#        disabled_feature;;
##        if [ ! -d "$MOONRAKER_OBICO_FOLDER" ]; then
##          error_msg "Moonraker Obico is not installed!"
##        else
##          run "remove_moonraker_obico" "remove_menu_ui_k1c_2025"
##        fi;;
#      21)
#        disabled_feature;;
##        if [ ! -d "$GUPPYFLO_FOLDER" ]; then
##          error_msg "GuppyFLO is not installed!"
##        else
##          run "remove_guppyflo" "remove_menu_ui_k1c_2025"
##        fi;;
#      22)
#        disabled_feature;;
##        if [ ! -d "$MOBILERAKER_COMPANION_FOLDER" ]; then
##          error_msg "Mobileraker Companion is not installed!"
##        else
##          run "remove_mobileraker_companion" "remove_menu_ui_k1c_2025"
##        fi;;
#      23)
#        disabled_feature;;
##        if [ ! -d "$OCTOAPP_COMPANION_FOLDER" ]; then
##          error_msg "OctoApp Companion is not installed!"
##        else
##          run "remove_octoapp_companion" "remove_menu_ui_k1c_2025"
##        fi;;
#      24)
#        disabled_feature;;
##        if ! grep -q "\[simplyprint\]" "$MOONRAKER_CFG"; then
##          error_msg "SimplyPrint is not installed!"
##        else
##          run "remove_simplyprint" "remove_menu_ui_k1c_2025"
##        fi;;
      B|b)
        clear; main_menu; break;;
      Q|q)
         clear; exit 0;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
  remove_menu_k1c_2025
}
