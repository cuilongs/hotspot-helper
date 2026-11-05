#!/usr/bin/env bash
set -euo pipefail
sudo apt remove hotspot-helper
printf '程序已卸载；个人热点密码和日志保留在用户配置/状态目录，方便以后重装。\n'
