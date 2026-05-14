#!/bin/sh

set -e

function reccon_message(){
  top_line
  title 'Reccon' "${yellow}"
  inner_line
  hr
  echo -e " в”‚ ${cyan}Reccon restores an interactive console shell on Creality      ${white}в”‚"
  echo -e " в”‚ ${cyan}systems by launching busybox sh through the console service. ${white}в”‚"
  hr
  bottom_line
}

function install_reccon(){
  reccon_message
  local yn
  while true; do
    install_msg "Reccon" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Downloading Reccon..."
        rm -rf /tmp/reccon-install
        mkdir -p /tmp/reccon-install
        "$CURL" -L "$RECCON_URL" -o /tmp/reccon.tar.gz
        echo -e "Info: Extracting Reccon..."
        tar -xzf /tmp/reccon.tar.gz -C /tmp/reccon-install
        if [ ! -f /tmp/reccon-install/reccon ]; then
          error_msg "reccon binary not found in archive!"
          rm -rf /tmp/reccon-install /tmp/reccon.tar.gz
          return 1
        fi
        echo -e "Info: Installing Reccon binary..."
        mkdir -p "$(dirname "$RECCON_FILE")"
        cp /tmp/reccon-install/reccon "$RECCON_FILE"
        chmod +x "$RECCON_FILE"
        echo -e "Info: Installing console init script..."
        cat > "$RECCON_SERVICE_FILE" <<'EOF'
#!/bin/sh

case "$1" in
    start)
        /usr/apps/overlay/sbin/reccon /bin/busybox sh >> /tmp/reccon.log 2>&1
    ;;
    *)
        exit 1
esac

exit 0
EOF
        chmod +x "$RECCON_SERVICE_FILE"
        rm -rf /tmp/reccon-install /tmp/reccon.tar.gz
        ok_msg "Reccon has been installed successfully!"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_reccon(){
  reccon_message
  local yn
  while true; do
    remove_msg "Reccon" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Removing Reccon binary..."
        rm -f "$RECCON_FILE"
        echo -e "Info: Removing console init script..."
        rm -f "$RECCON_SERVICE_FILE"
        ok_msg "Reccon has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
