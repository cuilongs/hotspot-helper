#!/usr/bin/env python3
"""Command-line entry point: gui | start | stop | status | password | plan."""
from pathlib import Path
import argparse
import getpass
import json
import subprocess
import sys
import os
import shutil
import platform
import time
import importlib.util
from hotspot_common import ROOT, CONFIG_FILE, DATA_DIR, state, stop, save_password, save_ssid, secret, connected_wifi, quick_enabled, save_interface


def main():
    parser = argparse.ArgumentParser(description='热点：保持本机 Wi-Fi 联网，同时开启热点。')
    parser.add_argument('--version', action='version', version='Hotspot Helper 0.4.2')
    parser.add_argument('action', nargs='?', default='gui', choices=['gui', 'start', 'stop', 'status', 'password', 'rename', 'plan', 'doctor', 'repair', 'enable-quick-start', 'disable-quick-start'])
    parser.add_argument('--interface', default='auto', help='指定已连接的上游 Wi-Fi 网卡，默认自动识别')
    parser.add_argument('--hold', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if os.geteuid() == 0:
            raise RuntimeError('请使用普通用户启动本应用，开启热点时会单独请求 sudo 认证。')
        if args.action == 'gui':
            import hotspot_app
            return hotspot_app.main()
        if args.action == 'doctor':
            tools = ['nmcli', 'iw', 'ip', 'iptables', 'dnsmasq', 'hostapd', 'sudo', 'systemd-run', 'systemctl']
            found = {name: shutil.which(name, path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin') for name in tools}
            try:
                import gi
                gi.require_version('Gtk', '4.0')
                from gi.repository import Gtk
                gtk = Gtk.get_major_version()
            except (ImportError, ValueError):
                gtk = None
            report = dict(version='0.4.2', system=platform.system(), machine=platform.machine(), tools=found, gtk=gtk, systemd_running=Path('/run/systemd/system').exists(), interfaces=connected_wifi(), config_path=str(CONFIG_FILE))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if all(found.values()) and gtk == 4 and Path('/run/systemd/system').exists() else 1
        if args.action == 'status':
            print(json.dumps(dict(state(), quick_start=quick_enabled()), ensure_ascii=False, indent=2))
        elif args.action == 'plan':
            return subprocess.call(['/usr/bin/python3', str(ROOT / 'start_standard_ap.py'), '--plan', '--interface', args.interface])
        elif args.action in ('enable-quick-start', 'disable-quick-start'):
            secret()
            action = 'enable' if args.action == 'enable-quick-start' else 'disable'
            print('此设置仅授权本助手的固定热点启动命令；管理员认证只需在设置时完成一次。', flush=True)
            result = subprocess.call(['sudo', '/usr/bin/python3', '-I', str(ROOT / 'quick_start_admin.py'), action, '--config', str(CONFIG_FILE)])
            if result == 0:
                args.hold = False
            return result
        elif args.action == 'start':
            current = state()
            if current['active'] and current.get('background'):
                print('热点已在后台运行，无需重复开启。')
                return 0
            config = secret()
            preferred = args.interface if args.interface != 'auto' else config.get('interface', 'auto')
            if args.interface != 'auto':
                save_interface(args.interface)
            if quick_enabled():
                print('正在启动后台热点，无需再次认证。', flush=True)
                result = subprocess.run(['sudo', '-n', '/usr/lib/hotspot-helper/control', 'start'])
            else:
                print('请在此窗口完成本机认证。可在面板中设置一次性授权，之后无需重复认证。', flush=True)
                command = ['sudo', '/usr/bin/python3', str(ROOT / 'service_launcher.py'), '--', '--allow-roam', '--config', str(CONFIG_FILE), '--interface', preferred]
                result = subprocess.run(command)
            if result.returncode:
                return result.returncode
            deadline = time.monotonic() + 75
            unit = 'hotspot-helper-' + str(os.getuid()) + '.service'
            while time.monotonic() < deadline:
                current = state()
                if current['active'] and current.get('background'):
                    print('热点已在后台运行。现在可关闭终端和面板；关闭热点请用面板按钮或 hotspot-helper stop。', flush=True)
                    args.hold = False
                    return 0
                status = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True)
                if status.stdout.strip() not in ('active', 'activating', 'reloading'):
                    raise RuntimeError(current.get('last_error') or '后台启动未完成。请运行 journalctl -u ' + unit + ' -n 20 --no-pager 查看原因。')
                time.sleep(.5)
            raise RuntimeError('后台启动超时，请查看热点状态或服务日志。')
        elif args.action in ('stop', 'repair'):
            print(stop())
        elif args.action == 'rename':
            save_ssid(input('新热点名称：'))
            print('名称已保存，重新开启热点后生效。')
        else:
            if state()['active']:
                raise ValueError('请先运行 hotspot-helper stop 关闭热点，再修改密码。')
            password = getpass.getpass('新热点密码（8～63 位英文字符）：')
            confirm = getpass.getpass('再次输入：')
            save_password(password, confirm)
            print('密码已修改，重新开启热点后生效；客户端设备 也须更新已保存的密码。')
        return 0
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。')
        return 1
    except Exception as error:
        print('未完成：' + str(error))
        return 1
    finally:
        if args.hold:
            try:
                input('按回车关闭窗口。')
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == '__main__':
    sys.exit(main())
