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

# Writes S48entware so /opt is mounted before camera services need Entware binaries.
# Removes the legacy S56entware startup script when migrating existing K1 2025 installs.
function k1_2025_write_entware_init_script() {
  echo "Info: Installing Entware boot mount (S48entware, before S50 camera services)..."
  rm -f "$INITD_FOLDER/S56entware"
  {
    echo '#!/bin/sh'
    echo '# Creality Helper Script — persistent Entware /opt (must run before S50*).'
    echo "ENTWARE_IMG=\"$ENTWARE_OPT_MOUNT\""
    echo 'mkdir -p /opt'
    echo 'if ! grep -q " /opt " /proc/mounts; then'
    echo '  mount -o loop "$ENTWARE_IMG" /opt || exit 1'
    echo 'fi'
    echo 'if [ -f /opt/etc/init.d/rc.unslung ]; then'
    echo '  /opt/etc/init.d/rc.unslung start'
    echo 'fi'
    echo 'mkdir -p /usr/libexec'
    echo 'if [ ! -e /usr/libexec/sftp-server ] && [ -f /opt/libexec/sftp-server ]; then'
    echo '  ln -sf /opt/libexec/sftp-server /usr/libexec/sftp-server'
    echo 'fi'
    echo 'if ! grep -qF "/opt/bin:/opt/sbin" /etc/profile 2>/dev/null; then'
    echo '  echo '"'"'export PATH=/opt/bin:/opt/sbin:$PATH'"'"' >> /etc/profile'
    echo 'fi'
  } > "$INITD_FOLDER/S48entware"
  chmod +x "$INITD_FOLDER/S48entware"
}

function k1_2025_opt_mount(){
  if [ -f "$ENTWARE_OPT_MOUNT" ]; then
    echo "Info: Existing /opt persistence file found. Skipping creation."
  else
    echo "Info: Creating /opt image for persistence..."
    dd if=/dev/zero of="$ENTWARE_OPT_MOUNT" bs=1M count=500
    mkfs.ext4 -F "$ENTWARE_OPT_MOUNT"
  fi

  k1_2025_write_entware_init_script

  echo "Info: Mounting Entware /opt for this session..."
  if ! grep -q " /opt " /proc/mounts; then
    mount -o loop "$ENTWARE_OPT_MOUNT" /opt
  fi
}

# Call when cameras are (re)installed so existing printers get S48 without reinstalling Entware.
function k1_2025_migrate_entware_boot_if_needed() {
  [ "$model" = "K1_2025" ] || return 0
  [ -f "$ENTWARE_OPT_MOUNT" ] || return 0
  k1_2025_write_entware_init_script
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
        if [ "$model" = "K1_2025" ]; then
          k1_2025_opt_mount
          $HS_FILES/fixes/curl -L "https://bin.entware.net/mipselsf-k3.4/installer/generic.sh" | sh
          export PATH=/opt/bin:/opt/sbin:$PATH
          sed -i '1s|.*|src/gz entware http://bin.tranducanh.com/mipselsf-k3.4|' /opt/etc/opkg.conf
          opkg update

          opkg install openssh-sftp-server
          # Symlink also created on boot by S48entware
          ln -sf /opt/libexec/sftp-server /usr/libexec/sftp-server
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
        if [ "$model" = "K1_2025" ]; then
          echo -e "Info: Removing Entware boot scripts (K1 2025)..."
          rm -f "$INITD_FOLDER/S48entware" "$INITD_FOLDER/S56entware"
          if grep -q " /opt " /proc/mounts; then
            umount /opt 2>/dev/null || true
          fi
        else
          echo -e "Info: Removing startup script..."
          rm -f /etc/init.d/S50unslung
          echo -e "Info: Removing directories..."
          rm -rf /usr/data/opt
        fi
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
