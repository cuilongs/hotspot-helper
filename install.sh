#!/usr/bin/env bash
set -euo pipefail
package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! command -v apt >/dev/null; then
  printf '此安装包面向使用 APT 的 Ubuntu/Debian 系统。\n'
  exit 1
fi
if [[ ! -f "$package_dir/hotspot-helper_0.4.0_all.deb" ]]; then
  printf '未找到 deb 包，请先运行 bash build_deb.sh。\n'
  exit 1
fi
sudo apt install "$package_dir/hotspot-helper_0.4.0_all.deb"
printf '\n安装完成：在应用菜单搜索“热点助手”，或运行 /usr/bin/hotspot-helper gui。\n'
if [[ -x "${XDG_BIN_HOME:-$HOME/.local/bin}/hotspot-helper" ]]; then
  printf '检测到用户目录中的旧版同名命令；本次请使用 /usr/bin/hotspot-helper 访问新版本。\n'
fi
