#!/usr/bin/env bash
set -euo pipefail
package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
package_root=$(mktemp -d)
trap 'rm -rf -- "$package_root"' EXIT
install -d "$package_root/DEBIAN" "$package_root/usr/bin" "$package_root/usr/lib/hotspot-helper" "$package_root/usr/share/applications" "$package_root/usr/share/icons/hicolor/scalable/apps" "$package_root/usr/share/doc/hotspot-helper"
for source_file in "$package_dir"/src/*.py; do
  install -m 644 "$source_file" "$package_root/usr/lib/hotspot-helper/"
done
install -m 755 "$package_dir/packaging/hotspot-helper" "$package_root/usr/bin/hotspot-helper"
install -m 644 "$package_dir/packaging/hotspot-helper.desktop" "$package_root/usr/share/applications/local.robotics.HotspotHelper.desktop"
install -m 644 "$package_dir/packaging/hotspot-helper.svg" "$package_root/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$package_dir/README.md" "$package_root/usr/share/doc/hotspot-helper/README.zh-CN.md"
install -m 755 "$package_dir/packaging/control" "$package_root/usr/lib/hotspot-helper/control"
install -m 755 "$package_dir/packaging/postrm" "$package_root/DEBIAN/postrm"
install -m 755 "$package_dir/packaging/prerm" "$package_root/DEBIAN/prerm"
installed_size=$(du -sk "$package_root/usr" | cut -f1)
cat > "$package_root/DEBIAN/control" <<EOF
Package: hotspot-helper
Version: 0.4.1
Section: net
Priority: optional
Architecture: all
Conflicts: jetson-hotspot
Replaces: jetson-hotspot
Maintainer: Local Robotics Project <root@localhost>
Installed-Size: $installed_size
Depends: systemd, python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, network-manager, iw, iproute2, iptables, dnsmasq-base, hostapd, sudo, x-terminal-emulator | ptyxis | gnome-terminal | xterm
Description: Native desktop and CLI Wi-Fi sharing helper
 Keeps a supported Wi-Fi adapter associated with a 2.4 GHz upstream AP
 while running a separate local AP, DHCP/DNS and scoped forwarding rules.
 Includes a GTK4 control panel, private per-user configuration and rollback.
EOF
export SOURCE_DATE_EPOCH=1793836800
chmod -R go-w "$package_root"
chmod 755 "$package_root"
dpkg-deb --root-owner-group --build "$package_root" "$package_dir/hotspot-helper_0.4.1_all.deb"
