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

function configure_go2rtc_k1c_2025(){
  local nginx_conf

  if [ -f "$MOONRAKER_CFG" ]; then
    if ! grep -q '^\[webcam chassis\]' "$MOONRAKER_CFG"; then
      echo -e "Info: Adding K1C 2025 chassis camera to moonraker.conf..."
      cat >> "$MOONRAKER_CFG" <<EOF

[webcam chassis]
enabled: True
location: printer
service: ipstream
target_fps: 15
target_fps_idle: 5
stream_url: /go2rtc/api/stream.mp4?src=chassis
snapshot_url: /go2rtc/api/frame.jpeg?src=chassis
flip_horizontal: False
flip_vertical: False
rotation: 0
aspect_ratio: 16:9
EOF
    else
      echo -e "Info: K1C 2025 chassis camera is already configured in moonraker.conf. Keeping existing camera URLs..."
    fi
  fi

  for nginx_conf in "$NGINX_FOLDER"/nginx/nginx.conf /etc/nginx/nginx.conf; do
    if [ -f "$nginx_conf" ]; then
      if ! grep -q 'location /go2rtc/' "$nginx_conf"; then
        echo -e "Info: Adding Nginx proxy for go2rtc in $nginx_conf..."
        sed -i '/location ~ \^\/(printer|api|access|machine|server)\/ {/i\
        location /go2rtc/ {\
            proxy_pass http://127.0.0.1:1984/;\
            proxy_http_version 1.1;\
            proxy_set_header Host $http_host;\
            proxy_set_header X-Real-IP $remote_addr;\
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
            proxy_buffering off;\
        }\
\
' "$nginx_conf"
      fi
    fi
  done
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
        mkdir -p "$(dirname "$GO2RTC_FILE")"
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
        if [ "$model" = "K1C_2025" ] && [ -d "$MOONRAKER_FOLDER" ]; then
          configure_go2rtc_k1c_2025
          stop_moonraker
          start_moonraker
          restart_nginx
        fi
        echo -e "Info: Starting Go2rtc service..."
        start_go2rtc
        ok_msg "Go2rtc has been installed successfully!"
        ok_msg "Stream URL: /go2rtc/api/stream.mp4?src=chassis"
        ok_msg "Snapshot URL: /go2rtc/api/frame.jpeg?src=chassis"
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
  go2rtc_message
  local yn
  while true; do
    remove_msg "Go2rtc" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Stopping Go2rtc service..."
        stop_go2rtc
        echo -e "Info: Removing files..."
        rm -f "$GO2RTC_SERVICE_FILE" "$GO2RTC_CONFIG_FILE" "$GO2RTC_FILE"
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
