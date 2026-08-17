#!/bin/sh

set -e

function customize_menu_ui_k1_2025() {
  top_line
  title '[ CUSTOMIZE MENU ]' "${yellow}"
  inner_line
  hr
  menu_option '1' 'Install' 'Creality Dynamic Logos for Fluidd'
  hr
  menu_option '2' 'Install' 'Block Creality Cloud Telemetry'
  menu_option '3' 'Remove' 'Block Creality Cloud Telemetry'
  menu_option '4' 'Disable' 'Creality Stock Services'
  menu_option '5' 'Restore' 'Creality Stock Services'
  hr
  menu_option '4' 'Retire' 'Nexusp Backend'
  menu_option '5' 'Restore' 'Nexusp Backend'
  hr
  inner_line
  hr
  bottom_menu_option 'b' 'Back to [Main Menu]' "${yellow}"
  bottom_menu_option 'q' 'Exit' "${darkred}"
  hr
  version_line "$(get_script_version)"
  bottom_line
}

function customize_menu_k1_2025() {
  clear
  customize_menu_ui_k1_2025
  local customize_menu_opt
  while true; do
    read -p " ${white}Type your choice and validate with Enter: ${yellow}" customize_menu_opt
    case "${customize_menu_opt}" in
      1)
        if [ -f "$FLUIDD_LOGO_FILE" ]; then
          error_msg "Creality Dynamic Logos for Fluidd are already installed!"
        elif [ ! -d "$FLUIDD_FOLDER" ]; then
          error_msg "Fluidd is needed, please install it first!"
        else
          run "install_creality_dynamic_logos" "customize_menu_ui_k1_2025"
        fi;;
      2)
        if [ -f "$CLOUD_BLOCK_SERVICE_FILE" ]; then
          error_msg "Block Creality Cloud Telemetry is already installed!"
        else
          run "install_block_creality_cloud" "customize_menu_ui_k1_2025"
        fi;;
      3)
        if [ ! -f "$CLOUD_BLOCK_SERVICE_FILE" ]; then
          error_msg "Block Creality Cloud Telemetry is not installed!"
        else
          run "remove_block_creality_cloud" "customize_menu_ui_k1_2025"
        fi;;
      4)
        if creality_services_absent; then
          error_msg "No Creality stock services were found on this firmware!"
        elif ! creality_services_pending; then
          error_msg "Creality Stock Services are already disabled!"
        else
          run "disable_creality_services" "customize_menu_ui_k1_2025"
        fi;;
      5)
        if creality_services_absent; then
          error_msg "No Creality stock services were found on this firmware!"
        elif ! creality_services_disabled_present; then
          error_msg "Creality Stock Services are not disabled!"
        else
          run "restore_creality_services" "customize_menu_ui_k1_2025"
        fi;;
      4)
        if nexusp_absent; then
          error_msg "No nexusp service was found on this firmware!"
        elif nexusp_retired && ! nexusp_resurrected; then
          error_msg "Nexusp Backend is already retired!"
        else
          # nexusp_resurrected falls through on purpose: a firmware update put
          # the service file back and retire_nexusp offers to re-apply the
          # rename, which is the only repair for it.
          run "retire_nexusp" "customize_menu_ui_k1_2025"
        fi;;
      5)
        if nexusp_absent; then
          error_msg "No nexusp service was found on this firmware!"
        elif ! nexusp_retired; then
          error_msg "Nexusp Backend is not retired!"
        else
          run "restore_nexusp" "customize_menu_ui_k1_2025"
        fi;;
      B|b)
        clear; main_menu; break;;
      Q|q)
         clear; exit 0;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
  customize_menu_k1_2025
}
