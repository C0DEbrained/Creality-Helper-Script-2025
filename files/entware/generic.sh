#!/bin/sh

unset LD_LIBRARY_PATH
unset LD_PRELOAD

LOADER=ld.so.1
GLIBC=2.27

echo -e "Info: Removing old directories..."
rm -rf /opt
rm -rf /usr/data/opt

echo -e "Info: Creating directory..."
mkdir -p /usr/data/opt

echo -e "Info: Linking folder..."
ln -nsf /usr/data/opt /opt

echo -e "Info: Creating subdirectories..."
for folder in bin etc lib/opkg tmp var/lock
do
  mkdir -p /usr/data/opt/$folder
done

echo -e "Info: Downloading opkg package manager from Entware repo..."

# entware.sh runs this file with `sh`, not `.`, and paths.sh does not export
# $CURL, so it is not visible here. Honour it if a caller ever exports it, and
# otherwise resolve the vendored curl relative to this script rather than
# hardcoding /usr/data/helper-script, which breaks any non-default clone path.
CURL="${CURL:-$(dirname "$0")/../fixes/curl}"
chmod 755 "$CURL"

primary_URL="https://bin.entware.net/mipselsf-k3.4/installer"

# -f so that an HTTP error status is reported as a failure. Without it curl
# exits 0 and writes the error page to the output path, which for /opt/bin/opkg
# means an HTML document is chmod 755'd and executed as root below.
download_files() {
  local url="$1"
  local output_file="$2"
  "$CURL" -fL "$url" -o "$output_file"
  return $?
}

# No mirror fallback: this binary is executed as root and there is no published
# checksum to verify a second source against. See the PR discussion before
# re-adding one.
if ! download_files "$primary_URL/opkg" "/opt/bin/opkg" ||
   ! download_files "$primary_URL/opkg.conf" "/opt/etc/opkg.conf"; then
  echo "Error: Failed to download opkg from ${primary_URL}."
  echo "       Check the printer's network and DNS, then run the installer again:"
  echo "         ping -c1 bin.entware.net"
  rm -rf /opt
  rm -rf /usr/data/opt
  exit 1
fi

# Sanity check, not authentication: opkg is about to be made executable and run
# as root. This catches truncated transfers and captive-portal or error-page
# bodies that arrive with a 200 status. The real opkg is ~877 KB.
if [ "$(wc -c < /opt/bin/opkg)" -lt 65536 ]; then
  echo "Error: The downloaded opkg is too small to be valid - refusing to run it."
  rm -rf /opt
  rm -rf /usr/data/opt
  exit 1
fi

echo -e "Info: Applying permissions..."
chmod 755 /opt/bin/opkg
chmod 777 /opt/tmp

echo -e "Info: Installing basic packages..."
/opt/bin/opkg update
/opt/bin/opkg install entware-opt

echo -e "Info: Installing SFTP server support..."
/opt/bin/opkg install openssh-sftp-server; ln -s /opt/libexec/sftp-server /usr/libexec/sftp-server

echo -e "Info: Configuring files..."
for file in passwd group shells shadow gshadow; do
  if [ -f /etc/$file ]; then
    ln -sf /etc/$file /opt/etc/$file
  else
    [ -f /opt/etc/$file.1 ] && cp /opt/etc/$file.1 /opt/etc/$file
  fi
done

[ -f /etc/localtime ] && ln -sf /etc/localtime /opt/etc/localtime

echo -e "Info: Applying changes in system profile..."
echo 'export PATH="/opt/bin:/opt/sbin:$PATH"' > /etc/profile.d/entware.sh

echo -e "Info: Adding startup script..."
echo '#!/bin/sh\n/opt/etc/init.d/rc.unslung "$1"' > /etc/init.d/S50unslung
chmod 755 /etc/init.d/S50unslung
