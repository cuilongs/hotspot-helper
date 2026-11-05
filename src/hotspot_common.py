"""Unprivileged state and local secret handling for the hotspot app."""
from pathlib import Path
import json
import os
import socket
import subprocess
import tempfile
import secrets
import shutil
import stat

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get('HOTSPOT_HELPER_CONFIG_DIR', str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'hotspot-helper')))
CONFIG_FILE = CONFIG_DIR / 'connection_secret.json'
DATA_DIR = Path(os.environ.get('HOTSPOT_HELPER_STATE_DIR', str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'hotspot-helper')))
STATE_FILE = Path('/run/cls-hotspot-helper/state.json')
SOCKET = Path('/run/cls-hotspot-helper/control.sock')


def secret():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not CONFIG_FILE.exists():
        data = dict(ssid='CLS-Hotspot', password=secrets.token_urlsafe(18), interface='auto')
        fd, temporary = tempfile.mkstemp(prefix='.initial_secret_', dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
            try:
                os.link(temporary, CONFIG_FILE)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    fd = os.open(CONFIG_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 16384:
            raise ValueError('热点配置所有者或文件格式异常。')
        if info.st_mode & 0o077:
            os.fchmod(stream.fileno(), 0o600)
        return json.load(stream)


def terminal_command(action):
    tail = ['/usr/bin/python3', str(ROOT / 'hotspot_cli.py'), action, '--hold']
    options = [
        ('ptyxis', ['--new-window', '--title=热点认证', '--']),
        ('gnome-terminal', ['--window', '--title=热点认证', '--']),
        ('konsole', ['--new-tab', '-e']),
        ('xfce4-terminal', ['--disable-server', '-x']),
        ('x-terminal-emulator', ['-e']),
        ('xterm', ['-e']),
    ]
    for name, flags in options:
        executable = shutil.which(name)
        if executable:
            return [executable, *flags, *tail]
    raise RuntimeError('未找到可用终端，请先安装 gnome-terminal 或 xterm。')


def connected_wifi():
    result = subprocess.run(['nmcli', '-t', '--escape', 'no', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'], capture_output=True, text=True, timeout=5, env=dict(os.environ, LC_ALL='C'))
    if result.returncode:
        raise RuntimeError('无法读取 NetworkManager 状态，请确认服务已启动。')
    return [parts[0] for row in result.stdout.splitlines() if len(parts := row.split(':')) == 3 and parts[1] == 'wifi' and parts[2] == 'connected' and parts[0] != 'hotspotap0']


def select_interface(preferred='auto'):
    devices = connected_wifi()
    if preferred and preferred != 'auto':
        if preferred not in devices:
            raise RuntimeError('指定的 Wi-Fi 网卡尚未连接：' + preferred)
        return preferred
    if len(devices) == 1:
        return devices[0]
    if not devices:
        raise RuntimeError('请先让电脑连接 Wi-Fi，再开启热点。')
    raise RuntimeError('检测到多个已连接的 Wi-Fi 网卡，请用 start --interface 网卡名 指定上游。')


def save_password(password, confirm):
    if Path('/sys/class/net/hotspotap0').exists():
        raise ValueError('请先关闭热点，再修改密码。')
    if not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password):
        raise ValueError('请输入 8～63 位英文字母、数字或符号。')
    if password != confirm:
        raise ValueError('两次输入不一致。')
    data = secret()
    data['password'] = password
    fd, name = tempfile.mkstemp(prefix='.hotspot_secret_', dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, CONFIG_FILE)
    finally:
        Path(name).unlink(missing_ok=True)


def state():
    data = {}
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        pass
    pid = data.get('pid')
    valid = False
    background = False
    if isinstance(pid, int) and pid > 1:
        try:
            args = Path('/proc', str(pid), 'cmdline').read_bytes().split(b'\0')
            known = [str(ROOT / 'start_standard_ap.py').encode()]
            valid = any(path in args for path in known)
            if valid:
                background = '/hotspot-helper-' in Path('/proc', str(pid), 'cgroup').read_text()
        except OSError:
            pass
    interface_exists = Path('/sys/class/net/hotspotap0').exists()
    needs_recovery = interface_exists and not valid and Path('/run/NetworkManager/conf.d/90-cls-hotspot-helper-ap.conf').exists()
    active = interface_exists and valid and data.get('owner_uid') == os.getuid()
    devices = []
    if active:
        try:
            for line in Path('/run/cls-hotspot-helper/dhcp/leases').read_text().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    devices.append(dict(ip=parts[2], name=parts[3]))
        except OSError:
            pass
    try:
        wifi = subprocess.run(['nmcli', '-g', 'GENERAL.CONNECTION', 'device', 'show', select_interface(secret().get('interface', 'auto'))], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        wifi = '读取中'
    return dict(active=active, background=background, needs_recovery=needs_recovery, pid=pid if valid else None, ssid=secret()['ssid'], upstream=data.get('upstream_ssid', wifi) if active else wifi, host_ip=data.get('host_ip') if active else None, devices=devices, last_error=data.get('error') if data.get('status') == 'FAILED' else None)


def stop():
    current = state()
    if current.get('needs_recovery'):
        result = subprocess.run(['sudo', '/usr/bin/python3', str(ROOT / 'start_standard_ap.py'), '--recover-only'])
        if result.returncode:
            raise RuntimeError('遗留热点尚未回收，请查看认证窗口提示。')
        return '遗留热点已回收。'
    if not current['active']:
        return '热点当前未运行。'
    if SOCKET.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(SOCKET))
            client.sendall(b'stop\n')
            if client.recv(64).strip() != b'STOPPING':
                raise RuntimeError('热点没有接受关闭请求。')
    else:
        raise RuntimeError('关闭接口暂不可用，请在热点运行窗口按 Ctrl+C。')
    return '正在关闭热点并恢复原 Wi-Fi，请稍候。'


def quick_enabled():
    try:
        profile = Path('/etc/hotspot-helper/users', str(os.getuid()) + '.json')
        data = json.loads(profile.read_text())
        return data.get('uid') == os.getuid() and Path(data['config']).resolve() == CONFIG_FILE.resolve()
    except (OSError, ValueError, KeyError):
        return False


def save_interface(preferred):
    select_interface(preferred)
    data = secret()
    data['interface'] = preferred
    fd, temporary = tempfile.mkstemp(prefix='.interface_secret_', dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, CONFIG_FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)
