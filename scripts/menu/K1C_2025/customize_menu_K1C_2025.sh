#!/bin/sh

set -e

function customize_menu_ui_k1c_2025() {
  top_line
  title '[ CUSTOMIZE MENU ]' "${yellow}"
  inner_line
  hr
  menu_option '1' 'Install' 'Creality Dynamic Logos for Fluidd'
  hr
  inner_line
  hr
  bottom_menu_option 'b' 'Back to [Main Menu]' "${yellow}"
  bottom_menu_option 'q' 'Exit' "${darkred}"
  hr
  version_line "$(get_script_version)"
  bottom_line
}

function customize_menu_k1c_2025() {
  clear
  customize_menu_ui_k1c_2025
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
          run "install_creality_dynamic_logos" "customize_menu_ui_k1c_2025"
        fi;;
      B|b)
        clear; main_menu; break;;
      Q|q)
         clear; exit 0;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
  customize_menu_k1c_2025
}
