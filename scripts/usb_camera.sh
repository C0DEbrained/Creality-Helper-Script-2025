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
  echo -e " в”‚ ${cyan}This allows to use the K1 2025 built-in camera with        ${white}в”‚"
  echo -e " в”‚ ${cyan}Fluidd and Mainsail through mjpg-streamer.                  ${white}в”‚"
  hr
  bottom_line
}

function configure_usb_camera_k1_2025(){
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

function configure_builtin_camera_k1_2025(){
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

# Makes mjpg-streamer available for the camera service this model actually runs.
# Returns non-zero (after reporting) when it cannot; callers must check.
function ensure_mjpg_streamer_packages(){
  if [ "$model" = "K1_2025" ]; then
    # The 2025 camera services hardcode /usr/bin/mjpg_streamer and
    # /usr/lib/mjpg-streamer, which the firmware supplies on a read-only
    # squashfs. opkg writes to /opt and cannot help here.
    [ -x /usr/bin/mjpg_streamer ] && return 0
    error_msg "mjpg_streamer not found in firmware; this model requires it."
    return 1
  fi

  # Legacy K1/3V3/3KE/10SE/E5M: the services read /opt/bin and /opt/lib, so
  # Entware is the source and the package list must be current.
  echo -e "Info: Updating Entware repository for mjpg-streamer packages..."
  "$ENTWARE_FILE" update || { error_msg "Could not refresh the package list."; return 1; }
  "$ENTWARE_FILE" install mjpg-streamer mjpg-streamer-input-http \
    mjpg-streamer-input-uvc mjpg-streamer-output-http mjpg-streamer-www
}

function disable_entware_builtin_mjpg_streamer(){
  if [ "$model" != "K1_2025" ]; then
    return
  fi

  if [ -f /opt/etc/init.d/S96mjpg-streamer ]; then
    echo -e "Info: Disabling conflicting Entware mjpg-streamer service..."
    set +e
    /opt/etc/init.d/S96mjpg-streamer stop
    set -e
    mv /opt/etc/init.d/S96mjpg-streamer /opt/etc/init.d/disabled.S96mjpg-streamer
  fi
}

function restore_entware_builtin_mjpg_streamer(){
  if [ "$model" != "K1_2025" ]; then
    return
  fi

  if [ -f /opt/etc/init.d/disabled.S96mjpg-streamer ]; then
    echo -e "Info: Restoring Entware mjpg-streamer service..."
    mv /opt/etc/init.d/disabled.S96mjpg-streamer /opt/etc/init.d/S96mjpg-streamer
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
        # Check packages before anything destructive: a failure here must leave
        # the printer exactly as it was, and must return to the menu rather
        # than propagate through helper.sh's global "set -e".
        echo -e "Info: Checking necessary packages..."
        if ! ensure_mjpg_streamer_packages; then
          error_msg "USB Camera Support has not been installed!"
          return 0
        fi
        if [ "$model" = "K1_2025" ]; then
          k1_2025_migrate_entware_boot_if_needed
          disable_entware_builtin_mjpg_streamer
        fi
        echo -e "Info: Copying file..."
        set +e
        [ "$USB_CAMERA_FILE" != "$USB_CAMERA_LEGACY_FILE" ] && [ -f "$USB_CAMERA_LEGACY_FILE" ] && "$USB_CAMERA_LEGACY_FILE" stop
        set -e
        rm -f "$USB_CAMERA_LEGACY_FILE"
        if [ "$model" = "K1_2025" ]; then
          cp "$USB_CAMERA_K1_2025_URL" "$USB_CAMERA_FILE"
        elif [ "$model" = "K1" ]; then
          cp "$USB_CAMERA_DUAL_URL" "$USB_CAMERA_FILE"
        else
          cp "$USB_CAMERA_SINGLE_URL" "$USB_CAMERA_FILE"
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
                sed -i 's/1280x720/640x480/g' "$USB_CAMERA_FILE"
              break;;
              720p|720P)
                echo -e "${white}"
                echo -e "Info: Applying change..."
              break;;
              1080p|1080p)
                echo -e "${white}"
                echo -e "Info: Applying change..."
                sed -i 's/1280x720/1920x1080/g' "$USB_CAMERA_FILE"
              break;;
              *)
                error_msg "Please select a correct choice!";;
            esac
          done
        fi
        chmod 755 "$USB_CAMERA_FILE"
        if [ "$model" = "K1_2025" ]; then
          configure_usb_camera_k1_2025
          if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
            stop_moonraker
            start_moonraker
          fi
        fi
        echo -e "Info: Starting service..."
        "$USB_CAMERA_FILE" start
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
  echo
  echo -e " ${yellow}Warning: Built-in camera access through CrealityPrint"
  echo -e " will stop working while this fix is installed.${white}"
  echo
  local yn
  while true; do
    install_msg "Built-in Camera Fix" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        # Same ordering rule as install_usb_camera: nothing destructive runs
        # until the packages are known to be in place.
        echo -e "Info: Checking necessary packages..."
        if ! ensure_mjpg_streamer_packages; then
          error_msg "Built-in Camera Fix has not been installed!"
          return 0
        fi
        k1_2025_migrate_entware_boot_if_needed
        disable_entware_builtin_mjpg_streamer
        echo -e "Info: Copying file..."
        set +e
        [ -f "$BUILTIN_CAMERA_LEGACY_FILE" ] && "$BUILTIN_CAMERA_LEGACY_FILE" stop
        set -e
        rm -f "$BUILTIN_CAMERA_LEGACY_FILE"
        cp "$BUILTIN_CAMERA_K1_2025_URL" "$BUILTIN_CAMERA_FILE"
        chmod 755 "$BUILTIN_CAMERA_FILE"
        configure_builtin_camera_k1_2025
        if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
          stop_moonraker
          start_moonraker
        fi
        echo -e "Info: Starting service..."
        "$BUILTIN_CAMERA_FILE" start
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
        "$BUILTIN_CAMERA_LEGACY_FILE" stop
        set -e
        echo -e "Info: Removing file..."
        rm -f "$BUILTIN_CAMERA_FILE"
        rm -f "$BUILTIN_CAMERA_LEGACY_FILE"
        restore_entware_builtin_mjpg_streamer
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
        if [ ! -f "$USB_CAMERA_FILE" ] && [ ! -f "$USB_CAMERA_LEGACY_FILE" ]; then
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
        "$USB_CAMERA_FILE" stop
        "$USB_CAMERA_LEGACY_FILE" stop
        set -e
        echo -e "Info: Removing file..."
        rm -f "$USB_CAMERA_FILE"
        rm -f "$USB_CAMERA_LEGACY_FILE"
        if [ "$model" = "K1_2025" ] && [ -f "$MOONRAKER_CFG" ]; then
          echo -e "Info: Removing USB Camera configurations in moonraker.conf file..."
          sed -i '/^\[webcam usb\]/,/^$/d' "$MOONRAKER_CFG"
          if [ -f "$INITD_FOLDER"/S56moonraker_service ]; then
            stop_moonraker
            start_moonraker
          fi
        fi
        echo -e "Info: Removing packages..."
        set +e
        if [ "$model" != "K1_2025" ] || { [ ! -f "$BUILTIN_CAMERA_FILE" ] && [ ! -f "$BUILTIN_CAMERA_LEGACY_FILE" ]; }; then
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
