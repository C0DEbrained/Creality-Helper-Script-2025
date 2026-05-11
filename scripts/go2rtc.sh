#!/bin/sh

set -e

function go2rtc_message(){
  top_line
  title 'Go2rtc' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}Go2rtc is a versatile camera streaming application             ${white}│"
  echo -e " │ ${cyan}On the K1C 2025, this can read and restream the                ${white}│"
  echo -e " │ ${cyan}camera feed directly for better stability and support          ${white}│"
  hr
  bottom_line
}


function install_go2rtc(){
  go2rtc_message
  local yn
  while true; do
    install_msg "Go2rtc" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Downloading go2rtc..."
        mkdir -p "$(dirname $GO2RTC_FILE)"
        $HS_FILES/fixes/curl -L "$GO2RTC_URL" -o "$GO2RTC_FILE"
        chmod +x "$GO2RTC_FILE"
        echo -e "Info: Copying service file..."
        if [ ! -f "$GO2RTC_SERVICE_FILE" ]; then
          cp "$GO2RTC_SERVICE_URL" "$GO2RTC_SERVICE_FILE"
          chmod +x "$GO2RTC_SERVICE_FILE"
        fi
        echo -e "Info: Copying config file..."
        if [ ! -f "$GO2RTC_CONFIG_FILE" ]; then
          cp "$GO2RTC_CONFIG_FILE_URL" "$GO2RTC_CONFIG_FILE"
        fi
        echo -e "Info: Starting Go2rtc service..."
        start_go2rtc
        ok_msg "Go2rtc has been installed successfully!"
        ok_msg "Stream URL: http://PRINTER_IP:1984/stream.mp4?src=chassis"
        ok_msg "Snapshot URL: http://PRINTER_IP:1984/frame.jpeg?src=chassis"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_go2rtc(){
  moonraker_nginx_message
  local yn
  while true; do
    remove_msg "Go2rtc" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Stopping Go2rtc service..."
        stop_go2rtc
        echo -e "Info: Removing files..."
        rm -f $GO2RTC_SERVICE_FILE $GO2RTC_CONFIG_FILE $GO2RTC_SERVICE_FILE
        ok_msg "Go2rtc has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}