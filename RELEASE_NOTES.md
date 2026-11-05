# 热点助手 0.4.0

中文 GTK4 面板与命令行工具，支持系统后台运行、异常退出恢复，以及可撤销的一次性本机授权。首次授权只保存受限的程序启动规则，不保存管理员密码。

```bash
sudo apt install ./hotspot-helper_0.4.0_all.deb
hotspot-helper gui
# 可选：在此电脑授权一次，之后启动不再重复认证
hotspot-helper enable-quick-start
```

依赖通过 APT 安装；无线网卡须支持 managed + AP 并发，目前采用 2.4 GHz 同信道方案。跨电脑完整启停仍需在目标电脑实测。
