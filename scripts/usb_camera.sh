#!/bin/sh

set -e

function usb_camera_message(){
  top_line
  title 'USB Camera Support' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}This allows to use third-party camera from your printer's    ${white}│"
  echo -e " │ ${cyan}USB port.                                                    ${white}│"
  hr
  bottom_line
}

function builtin_camera_message(){
  top_line
  title 'Built-in Camera Fix' "${yellow}"
  inner_line
  hr
  echo -e " в”‚ ${cyan}This allows to use the K1C 2025 built-in camera with        ${white}в”‚"
  echo -e " в”‚ ${cyan}Fluidd and Mainsail through mjpg-streamer.                  ${white}в”‚"
  hr
  bottom_line
}

function configure_usb_camera_k1c_2025(){
  local usb_dev

  if [ ! -f "$MOONRAKER_CFG" ]; then
    return
  fi

  usb_dev=$(v4l2-ctl --list-devices | grep -A1 usb | sed 's/^[[:space:]]*//g' | grep '^/dev' | grep -v '^/dev/video0$' | head -n 1)
  if [ -n "$usb_dev" ]; then
    echo -e "Info: Configuring USB camera in moonraker.conf..."
    sed -i '/^\[webcam usb\]/,/^$/d' "$MOONRAKER_CFG"
    cat >> "$MOONRAKER_CFG" <<EOF

[webcam usb]
enabled: True
location: printer
service: mjpegstreamer
target_fps: 15
target_fps_idle: 5
stream_url: /webcam3/?action=stream
snapshot_url: /webcam3/?action=snapshot
flip_horizontal: False
flip_vertical: False
rotation: 0
aspect_ratio: 16:9
EOF
  fi
}

function configure_builtin_camera_k1c_2025(){
  if [ ! -f "$MOONRAKER_CFG" ]; then
    return
  fi

  echo -e "Info: Configuring built-in camera in moonraker.conf..."
  sed -i '/^\[webcam chassis\]/,/^$/d' "$MOONRAKER_CFG"
  cat >> "$MOONRAKER_CFG" <<EOF

[webcam chassis]
enabled: True
location: printer
service: mjpegstreamer
target_fps: 15
target_fps_idle: 5
stream_url: /webcam/?action=stream
snapshot_url: /webcam/?action=snapshot
flip_horizontal: False
flip_vertical: False
rotation: 0
aspect_ratio: 16:9
EOF
}

function ensure_mjpg_streamer_packages(){
  if "$ENTWARE_FILE" list | grep -q '^mjpg-streamer '; then
    return
  fi

  if [ "$model" = "K1C_2025" ]; then
    echo -e "Info: Updating Entware repository for mjpg-streamer packages..."
    sed -i '1s|.*|src/gz entware http://bin.tranducanh.com/mipselsf-k3.4|' /opt/etc/opkg.conf
    "$ENTWARE_FILE" update
  fi

  if ! "$ENTWARE_FILE" list | grep -q '^mjpg-streamer '; then
    error_msg "mjpg-streamer packages are not available in the configured Entware repository!"
    return 1
  fi
}

function install_usb_camera(){
  usb_camera_message
  local yn
  while true; do
    install_msg "USB Camera Support" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Copying file..."
        if [ "$model" = "K1C_2025" ]; then
          cp "$USB_CAMERA_K1C_2025_URL" "$INITD_FOLDER"/S50usb_camera
        elif [ "$model" = "K1" ]; then
          cp "$USB_CAMERA_DUAL_URL" "$INITD_FOLDER"/S50usb_camera
        else
          cp "$USB_CAMERA_SINGLE_URL" "$INITD_FOLDER"/S50usb_camera
          echo
          echo -e " ${darkred}Be careful with the 1080p resolution!"
          echo -e " It takes more resources and timelapses are larger and take longer to convert.${white}"
          echo -e " 720p is a good compromise between quality and performance."
          echo -e " Make sure your camera is compatible with the chosen resolution."
          echo
          local resolution
          while true; do
            read -p " What camera resolution do you want to apply? (${yellow}480p${white}/${yellow}720p${white}/${yellow}1080p${white}): ${yellow}" resolution
            case "${resolution}" in
              480p|480P)
                echo -e "${white}"
                echo -e "Info: Applying change..."
                sed -i 's/1280x720/640x480/g' "$INITD_FOLDER"/S50usb_camera
              break;;
              720p|720P)
                echo -e "${white}"
                echo -e "Info: Applying change..."
              break;;
              1080p|1080p)
                echo -e "${white}"
                echo -e "Info: Applying change..."
                sed -i 's/1280x720/1920x1080/g' "$INITD_FOLDER"/S50usb_camera
              break;;
              *)
                error_msg "Please select a correct choice!";;
            esac
          done
        fi
        chmod 755 "$INITD_FOLDER"/S50usb_camera
        echo -e "Info: Installing necessary packages..."
        ensure_mjpg_streamer_packages
        "$ENTWARE_FILE" update && "$ENTWARE_FILE" install mjpg-streamer mjpg-streamer-input-http mjpg-streamer-input-uvc mjpg-streamer-output-http mjpg-streamer-www
        echo -e "Info: Starting service..."
        "$INITD_FOLDER"/S50usb_camera start
        if [ "$model" = "K1C_2025" ]; then
          configure_usb_camera_k1c_2025
          if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
            stop_moonraker
            start_moonraker
          fi
        fi
        ok_msg "USB Camera Support has been installed successfully!"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function install_builtin_camera(){
  builtin_camera_message
  local yn
  while true; do
    install_msg "Built-in Camera Fix" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Copying file..."
        cp "$BUILTIN_CAMERA_K1C_2025_URL" "$BUILTIN_CAMERA_FILE"
        chmod 755 "$BUILTIN_CAMERA_FILE"
        echo -e "Info: Installing necessary packages..."
        ensure_mjpg_streamer_packages
        "$ENTWARE_FILE" update && "$ENTWARE_FILE" install mjpg-streamer mjpg-streamer-input-http mjpg-streamer-input-uvc mjpg-streamer-output-http mjpg-streamer-www
        echo -e "Info: Starting service..."
        "$BUILTIN_CAMERA_FILE" start
        configure_builtin_camera_k1c_2025
        if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
          stop_moonraker
          start_moonraker
        fi
        ok_msg "Built-in Camera Fix has been installed successfully!"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_builtin_camera(){
  builtin_camera_message
  local yn
  while true; do
    remove_msg "Built-in Camera Fix" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Stopping service..."
        set +e
        "$BUILTIN_CAMERA_FILE" stop
        set -e
        echo -e "Info: Removing file..."
        rm -f "$BUILTIN_CAMERA_FILE"
        if [ -f "$MOONRAKER_CFG" ]; then
          echo -e "Info: Removing built-in camera configuration in moonraker.conf file..."
          sed -i '/^\[webcam chassis\]/,/^$/d' "$MOONRAKER_CFG"
          if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
            stop_moonraker
            start_moonraker
          fi
        fi
        echo -e "Info: Removing packages..."
        set +e
        if [ ! -f "$USB_CAMERA_FILE" ]; then
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-www
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-output-http
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-input-uvc
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-input-http
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer
        fi
        set -e
        ok_msg "Built-in Camera Fix has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_usb_camera(){
  usb_camera_message
  local yn
  while true; do
    remove_msg "USB Camera Support" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Stopping service..."
        set +e
        "$INITD_FOLDER"/S50usb_camera stop
        set -e
        echo -e "Info: Removing file..."
        rm -f "$INITD_FOLDER"/S50usb_camera
        if [ "$model" = "K1C_2025" ] && [ -f "$MOONRAKER_CFG" ]; then
          echo -e "Info: Removing USB Camera configurations in moonraker.conf file..."
          sed -i '/^\[webcam usb\]/,/^$/d' "$MOONRAKER_CFG"
          if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
            stop_moonraker
            start_moonraker
          fi
        fi
        echo -e "Info: Removing packages..."
        set +e
        if [ "$model" != "K1C_2025" ] || [ ! -f "$BUILTIN_CAMERA_FILE" ]; then
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-www
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-output-http
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-input-uvc
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer-input-http
          "$ENTWARE_FILE" --autoremove remove mjpg-streamer
        fi
        set -e
        ok_msg "USB Camera Support has been removed successfully!"
        echo -e "   Please reboot your printer by using power switch on back!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
