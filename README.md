# 热点助手 0.4.1

安装包和迁移包位于 [`downloads/`](downloads/)，也可从 GitHub Releases 获取。

中文 GTK4 桌面工具：让 Linux 电脑保持 Wi-Fi 联网，同时为其他设备提供热点。支持系统后台运行、一次性授权和异常退出恢复。源码与迁移包不包含原电脑的密码、网络配置或设备工程。

## 安装

面向使用 NetworkManager 和 systemd 的 Ubuntu/Debian 桌面系统，需要 Python 3.10 及以上、GTK4。安装时 APT 会获取相应系统依赖，通常需要联网。应在 Linux 宿主机运行，不放入 ROS Docker 容器。

下载 `.deb` 后，在它所在目录运行：

```bash
sudo apt install ./hotspot-helper_0.4.1_all.deb
hotspot-helper gui
```

也可解压完整迁移包，在解压目录运行 `bash install.sh`。安装后在应用菜单搜索“热点助手”。无需复制 ros_ws。

## 首次使用与一次性授权

1. 先让电脑连接 Wi-Fi，再打开热点助手。
2. 面板会显示首次生成的热点密码；未开启热点时可以修改。
3. 可点击“一次性授权”，或运行以下命令，在本机完成一次管理员认证：

```bash
hotspot-helper enable-quick-start
```

4. 之后从面板开启热点不会再弹认证终端；关闭也不需要重复认证。
5. 在客户端连接面板显示的热点名称、密码，地址由 DHCP 分配。

默认不自动启用免重复认证。没有设置该授权时，每次启动仍会请求管理员认证。普通用户启动面板即可，不要用 sudo 运行整个图形应用。

授权不会保存管理员密码。系统只保存当前用户的固定规则，允许执行 `/usr/lib/hotspot-helper/control start`；该入口由管理员拥有，使用隔离的 Python 环境并校验注册用户与私有配置，只启动本助手的固定后台服务。授权仅留在本机，新电脑须重新授权。撤销命令：

```bash
hotspot-helper disable-quick-start
```

## 后台运行和关机

启动成功后，认证终端和图形面板都可以关闭，热点继续由 systemd 管理。关闭热点使用面板按钮或 `hotspot-helper stop`，不是关闭终端。

不设置开机自启。电脑关机或断电会断开热点及其连接；重新开机后需要手动开启。已保存的热点名称和密码保留，临时接口和规则随系统重启清除。若仅管理进程异常退出留下资源，再次开启会在取得管理锁、确认本助手的配置标记后回收并重新启动；可用 `repair` 单独回收。

## 命令

```bash
hotspot-helper --version
hotspot-helper gui
hotspot-helper start
hotspot-helper status
hotspot-helper stop
hotspot-helper password
hotspot-helper rename
hotspot-helper doctor
hotspot-helper plan
hotspot-helper repair
hotspot-helper enable-quick-start
hotspot-helper disable-quick-start

# 多个无线网卡同时连接时指定上游，名称以实际电脑为准
hotspot-helper start --interface wlan0
```

改密码须先关闭热点，保存后也要更新客户端中已保存的 Wi-Fi 密码。修改名称和网络配置不会保存管理员登录密码。

## 硬件和换网络

网卡及驱动必须支持 managed + AP 并发，当前方案使用相同的 2.4 GHz 信道。先关闭热点，再连接新的 Wi-Fi，重新开启时自动识别当前网卡与同名 2.4 GHz 接入点；如果路由器的 2.4 GHz、5 GHz 名称不同，先连接 2.4 GHz 名称。找不到可用接入点或硬件拒绝并发时会报告原因并回退。

默认热点名 CLS-Hotspot；从旧版迁移时可以保留原名称、密码。默认网段为 `192.168.77.0/24`，发生冲突时依次尝试 `192.168.78.0/24`、`192.168.79.0/24`、`10.42.77.0/24`，实际地址以状态输出为准。

`.deb` 标记为 Architecture: all，不捆绑某台电脑编译的 hostapd，依赖由目标电脑自己的 APT 安装。代码可移植不等于所有型号的网卡已通过实测，换电脑后仍应完成 ping、外网和启停检查。

## 配置、日志与授权位置

- 个人热点配置：`~/.config/hotspot-helper/connection_secret.json`，权限 600。每台电脑首次生成独立密码。
- 可遵循 `XDG_CONFIG_HOME`；排查时支持 `HOTSPOT_HELPER_CONFIG_DIR` 指定应用配置目录。
- 运行状态与临时配置：`/run/cls-hotspot-helper/`。
- 后台服务：`hotspot-helper-用户UID.service`。查看日志：

```bash
journalctl -u "hotspot-helper-$(id -u).service" -n 40 --no-pager
```

- 启用一次性授权后，规则位于 `/etc/sudoers.d/hotspot-helper-UID`，注册信息位于 `/etc/hotspot-helper/users/UID.json`。这些本机文件不包含在发布包中。

## 卸载和旧版本

```bash
sudo apt remove hotspot-helper
# 或解压包中执行 bash uninstall.sh
```

卸载先停止属于本包的后台热点，并清除本应用生成的一次性授权。个人热点密码保留，便于以后重装。升级可能会停止正在运行的热点，升级后手动重新开启。

如果用户目录中还保留旧版同名命令，可用 `/usr/bin/hotspot-helper --version` 和 `/usr/bin/hotspot-helper gui` 确认系统安装版。

## 源码与验证范围

`src/` 为 Python 源码，`packaging/` 为系统入口、图标及卸载处理。无需连接客户端设备或启动 Docker/ROS 即可打包：

```bash
bash build_deb.sh
```

本机已实测后台运行、异常退出恢复、一次性授权，以及不使用缓存密码的受限启动；此前完成双向 ping、SSH 文件传输与 HTTPS 访问。跨电脑完整启停仍需在目标电脑实测。

## 0.4.1 名称修改

面板热点名称旁新增“修改名称”按钮。先关闭热点，输入新名称并保存，再开启即可生效。支持中文，名称最多为 32 个 UTF-8 字节。名称与密码分开保存，修改名称不会改变已有密码或免重复认证授权。命令行入口为 `hotspot-helper rename`。
