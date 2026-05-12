#!/bin/sh

set -e

function entware_message(){
  top_line
  title 'Entware' "${yellow}"
  inner_line
  hr
  echo -e " │ ${cyan}Entware is a software repository for devices which use Linux ${white}│"
  echo -e " │ ${cyan}kernel. It allows packages to be added to your printer.      ${white}│"
  hr
  bottom_line
}

function k1c_2025_opt_mount(){
  if [ -f $ENTWARE_OPT_MOUNT ]; then
    echo "Info: Existing /opt persistence file found. Skipping creation."
  else
    # Create 500mb image
    echo "Info: Creating /opt image for persistence..."
    dd if=/dev/zero of=$ENTWARE_OPT_MOUNT bs=1M count=500
    mkfs.ext4 -F $ENTWARE_OPT_MOUNT
  fi

  if [ ! -f $INITD_FOLDER/S56entware ]; then
    echo "Adding entware script to $INITD_FOLDER"
    cat << EOF > $INITD_FOLDER/S56entware
    #!/bin/sh
    mkdir -p /opt
    mount -o loop $ENTWARE_OPT_MOUNT /opt

    # Start Entware services (if any are installed like SSH, lighttpd, etc.)
    if [ -f /opt/etc/init.d/rc.unslung ]; then
        /opt/etc/init.d/rc.unslung start
    fi

    ln -s /opt/libexec/sftp-server /usr/libexec/sftp-server

    # Inject Entware into the system PATH globally for all users
    echo 'export PATH=/opt/bin:/opt/sbin:$PATH' >> /etc/profile
EOF
    chmod +x $INITD_FOLDER/S56entware
  fi

  #Manually mount for now
  mount -o loop $ENTWARE_OPT_MOUNT /opt
}

function install_entware(){
  entware_message
  local yn
  while true; do
    install_msg "Entware" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Running Entware installer..."
        set +e
        if [ "$model" = "K1C_2025" ]; then
          k1c_2025_opt_mount
          $HS_FILES/fixes/curl -L "https://bin.entware.net/mipselsf-k3.4/installer/generic.sh" | sh
          export PATH=/opt/bin:/opt/sbin:$PATH
          sed -i '1s|.*|src/gz entware http://bin.tranducanh.com/mipselsf-k3.4|' /opt/etc/opkg.conf
          opkg update

          opkg install openssh-sftp-server
          #Manually link. Will be done on boot by S56entware
          ln -s /opt/libexec/sftp-server /usr/libexec/sftp-server
        else
          prepare_opt
          chmod 755 "$ENTWARE_URL"
          sh "$ENTWARE_URL"
        fi

        set -e
        ok_msg "Entware has been installed successfully!"
        echo -e "   Disconnect and reconnect SSH session, and you can now install packages with: ${yellow}opkg install <packagename>${white}"
        return;;
      N|n)
        error_msg "Installation canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}

function remove_entware(){
  entware_message
  local yn
  while true; do
    remove_msg "Entware" yn
    case "${yn}" in
      Y|y)
        echo -e "${white}"
        echo -e "Info: Removing startup script..."
        rm -f /etc/init.d/S50unslung
        echo -e "Info: Removing directories..."
        rm -rf /usr/data/opt
        if [ -L /opt ]; then
          rm /opt
          mkdir -p /opt
          chmod 755 /opt
        fi
        echo -e "Info: Removing SFTP server symlink..."
        [ -L /usr/libexec/sftp-server ] && rm /usr/libexec/sftp-server
        echo -e "Info: Removing changes in system profile..."
        rm -f /etc/profile.d/entware.sh
        sed -i 's/\/opt\/bin:\/opt\/sbin:\/bin:/\/bin:/' /etc/profile
        ok_msg "Entware has been removed successfully!"
        return;;
      N|n)
        error_msg "Deletion canceled!"
        return;;
      *)
        error_msg "Please select a correct choice!";;
    esac
  done
}
