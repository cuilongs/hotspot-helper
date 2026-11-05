"""Temporary same-channel AP sharing. Explicit --allow-roam is required.

Run in the visible authentication terminal. Ctrl+C tears down this AP and
restores the original upstream profile if our temporary profile is still active.
"""
from pathlib import Path
import argparse
import fcntl
import json
import os
import pwd
import re
import signal
import socket
import subprocess
import time
import ipaddress
import stat
import sys
from hotspot_common import select_interface
from hotspot_recovery import recover

ROOT = Path(__file__).resolve().parent
RUNTIME = Path('/run/cls-hotspot-helper')
STA, AP = None, 'hotspotap0'
NM_CONF = Path('/run/NetworkManager/conf.d/90-cls-hotspot-helper-ap.conf')


def command(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=40, env=dict(os.environ, LC_ALL='C'))
    if check and result.returncode:
        raise RuntimeError('命令失败：' + ' '.join(args[:4]) + '\n' + result.stderr.strip())
    return result


def active_uuid():
    return command(['nmcli', '-g', 'GENERAL.CON-UUID', 'dev', 'show', STA]).stdout.strip()


def upstream_plan(rescan=False):
    original = active_uuid()
    if not original or original == '--':
        raise RuntimeError('请先让本机连接一个 Wi-Fi，再开启热点。')
    ssid = command(['nmcli', '--escape', 'no', '-g', '802-11-wireless.ssid', 'connection', 'show', 'uuid', original]).stdout.strip()
    aps = command(['nmcli', '-t', '--escape', 'no', '-f', 'BSSID,SSID,FREQ,SIGNAL', 'device', 'wifi', 'list', 'ifname', STA, '--rescan', 'yes' if rescan else 'no']).stdout
    candidates = []
    for row in aps.splitlines():
        match = re.fullmatch(r'([0-9a-fA-F:]{17}):(.*):(\d+)(?: MHz)?:(\d+)', row)
        if match:
            bssid, name, frequency, strength = match.groups()
            frequency = int(frequency)
            if name == ssid and 2412 <= frequency <= 2472 and (frequency - 2412) % 5 == 0:
                candidates.append(dict(bssid=bssid, frequency=frequency, channel=(frequency - 2407) // 5, signal=int(strength)))
    if not candidates:
        raise RuntimeError('当前 Wi-Fi“' + ssid + '”没有可见的同名 2.4 GHz 接入点。请先连接它的 2.4 GHz 网络，或使用第二块无线网卡。原连接未修改。')
    link = command(['/usr/sbin/iw', 'dev', STA, 'link']).stdout
    current = re.search(r'Connected to ([0-9a-f:]{17})', link, re.I)
    candidates.sort(key=lambda ap: (bool(current and ap['bssid'].lower() == current[1].lower()), ap['signal']), reverse=True)
    return dict(original=original, ssid=ssid, **candidates[0])


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)


def save_result(data):
    data['owner_uid'] = int(os.environ.get('SUDO_UID', str(os.getuid())))
    path = RUNTIME / 'state.json'
    private_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.chmod(path, 0o644)


def load_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        uid = int(os.environ.get('SUDO_UID', str(os.getuid())))
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_size > 16384 or info.st_mode & 0o077:
            raise RuntimeError('配置必须为调用用户拥有的普通私有文件（权限 600）。')
        value = json.load(stream)
    ssid, password = value.get('ssid', ''), value.get('password', '')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(c in ssid for c in '\n\r\0'):
        raise ValueError('热点名称格式异常。')
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password):
        raise ValueError('热点密码须为 8～63 位英文字符。')
    return value


def choose_network():
    addresses = json.loads(command(['/usr/sbin/ip', '-j', '-4', 'address', 'show']).stdout)
    used = [ipaddress.ip_interface(str(info['local']) + '/' + str(info['prefixlen'])).network for item in addresses for info in item.get('addr_info', []) if info.get('family') == 'inet']
    for cidr in ['192.168.77.0/24', '192.168.78.0/24', '192.168.79.0/24', '10.42.77.0/24']:
        network = ipaddress.ip_network(cidr)
        if not any(network.overlaps(other) for other in used):
            return network
    raise RuntimeError('候选热点网段均与现有网络冲突，原连接未修改。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    global STA
    parser.add_argument('--recover-only', action='store_true', help='仅回收本助手退出后的遗留热点')
    parser.add_argument('--interface', default='auto', help='上游 Wi-Fi 网卡，默认自动识别')
    parser.add_argument('--config', help='调用用户的私有热点配置路径')
    parser.add_argument('--allow-roam', action='store_true')
    parser.add_argument('--plan', action='store_true', help='只读取当前 Wi-Fi 和可用的 2.4 GHz 接入点')
    args = parser.parse_args()
    if args.recover_only:
        if os.geteuid() != 0:
            raise RuntimeError('恢复热点需要本机认证。')
        RUNTIME.mkdir(exist_ok=True, mode=0o755)
        with (RUNTIME / 'standard_ap.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            recover(RUNTIME, AP, NM_CONF, 'cls-hotspot-helper-share', command)
            save_result(dict(status='STOPPED'))
        return
    STA = select_interface(args.interface)
    if args.plan:
        print(json.dumps(upstream_plan(), ensure_ascii=False, indent=2))
        return
    if not args.allow_roam:
        parser.error('尚未授权短暂切换到同一 Wi-Fi 的 2.4 GHz 接入点；未执行任何网络修改。')
    if os.geteuid() != 0:
        raise SystemExit('请在本机认证窗口通过 sudo 启动。')
    if not args.config:
        parser.error('缺少私有配置文件，请使用 hotspot-helper start 启动。')
    secret = load_config(args.config)
    RUNTIME.mkdir(exist_ok=True, mode=0o755)
    runtime_info = RUNTIME.lstat()
    if not stat.S_ISDIR(runtime_info.st_mode) or runtime_info.st_uid != 0 or runtime_info.st_mode & 0o022:
        raise RuntimeError('运行目录权限异常，未修改网络。')
    lock = (RUNTIME / 'standard_ap.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if NM_CONF.exists() or Path('/sys/class/net', AP).exists():
        recover(RUNTIME, AP, NM_CONF, 'cls-hotspot-helper-share', command)
    plan = upstream_plan(rescan=True)
    original, temporary = plan['original'], None
    ssid, password = secret['ssid'], secret['password']
    if '\n' in ssid or '\n' in password or not 8 <= len(password) <= 63:
        raise ValueError('热点配置格式异常')
    hostapd = Path('/usr/sbin/hostapd')
    if not hostapd.is_file():
        raise RuntimeError('缺少系统 hostapd，请先运行安装脚本安装依赖。')
    phy = Path('/sys/class/net', STA, 'phy80211').resolve().name
    capabilities = command(['/usr/sbin/iw', 'phy', phy, 'info']).stdout
    if not re.search(r'^\s*\* AP\s*$', capabilities, re.M):
        raise RuntimeError('当前无线网卡未报告 AP 模式支持，原连接未修改。')
    network = choose_network()
    cidr, gateway = str(network), str(network[1])
    processes, rules = [], []
    switched = conf_created = interface_created = False
    old_forward = Path('/proc/sys/net/ipv4/ip_forward').read_text().strip()
    running = True
    control = None

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    try:
        print('上游 Wi-Fi：' + plan['ssid'] + '；将临时固定到 2.4 GHz 信道 ' + str(plan['channel']) + '，失败自动回退。', flush=True)
        clone_name = 'CLS-Hotspot-Upstream-' + str(os.getpid())
        command(['nmcli', 'connection', 'clone', '--temporary', 'uuid', original, clone_name])
        temporary = command(['nmcli', '-g', 'connection.uuid', 'connection', 'show', clone_name]).stdout.strip()
        command(['nmcli', 'connection', 'modify', '--temporary', 'uuid', temporary, 'connection.autoconnect', 'no', '802-11-wireless.band', 'bg', '802-11-wireless.channel', str(plan['channel']), '802-11-wireless.bssid', plan['bssid'], '802-11-wireless.cloned-mac-address', 'preserve'])
        if active_uuid() != original:
            raise RuntimeError('当前连接在准备期间发生变化，未执行切换。')
        switched = True
        command(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', temporary, 'ifname', STA])
        link = command(['/usr/sbin/iw', 'dev', STA, 'link']).stdout
        if active_uuid() != temporary or 'freq: ' + str(plan['frequency']) not in link:
            raise RuntimeError('上游没有连接到预定的 2.4 GHz 接入点')
        NM_CONF.parent.mkdir(parents=True, exist_ok=True)
        NM_CONF.write_text('[device-cls-hotspot-helper-ap]\nmatch-device=interface-name:hotspotap0\nmanaged=0\n')
        conf_created = True
        command(['nmcli', 'general', 'reload', 'conf'])
        command(['/usr/sbin/iw', 'dev', STA, 'interface', 'add', AP, 'type', '__ap'])
        interface_created = True
        config = RUNTIME / 'hostapd.conf'
        private_write(config, f'interface={AP}\ndriver=nl80211\nssid={ssid}\nhw_mode=g\nchannel={plan["channel"]}\nwmm_enabled=1\nauth_algs=1\nwpa=2\nwpa_passphrase={password}\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n')
        ap_log = RUNTIME / 'hostapd.log'
        with ap_log.open('w') as log:
            ap_process = subprocess.Popen([str(hostapd), str(config)], stdout=log, stderr=subprocess.STDOUT)
        processes.append(ap_process)
        for _ in range(80):
            if ap_process.poll() is not None:
                raise RuntimeError('热点无线服务未能启动；日志在 /run/cls-hotspot-helper/hostapd.log')
            if 'AP-ENABLED' in ap_log.read_text():
                break
            time.sleep(.1)
        else:
            raise RuntimeError('热点启动超时')
        command(['/usr/sbin/ip', 'addr', 'add', gateway + '/24', 'dev', AP])
        command(['/usr/sbin/ip', 'link', 'set', AP, 'up'])
        account = pwd.getpwnam('nobody')
        dhcp_dir = RUNTIME / 'dhcp'
        dhcp_dir.mkdir(exist_ok=True)
        os.chown(dhcp_dir, account.pw_uid, account.pw_gid)
        dns_args = ['/usr/sbin/dnsmasq', '--keep-in-foreground', '--conf-file=/dev/null', '--user=' + account.pw_name, '--bind-interfaces', '--interface=' + AP, '--listen-address=' + gateway, '--dhcp-range=' + str(network[10]) + ',' + str(network[50]) + ',255.255.255.0,12h', '--dhcp-option=3,' + gateway, '--dhcp-option=6,' + gateway, '--dhcp-leasefile=' + str(dhcp_dir / 'leases'), '--pid-file=' + str(RUNTIME / 'dnsmasq.pid'), '--resolv-file=' + ('/run/systemd/resolve/resolv.conf' if Path('/run/systemd/resolve/resolv.conf').exists() else '/etc/resolv.conf')]
        with (RUNTIME / 'dnsmasq.log').open('w') as log:
            dns = subprocess.Popen(dns_args, stdout=log, stderr=subprocess.STDOUT)
        processes.append(dns)
        time.sleep(.5)
        if dns.poll() is not None:
            raise RuntimeError('DHCP 服务启动失败；日志在 /run/cls-hotspot-helper/dnsmasq.log')
        Path('/proc/sys/net/ipv4/ip_forward').write_text('1\n')
        planned = [
            ['-t', 'nat', '-A', 'POSTROUTING', '-s', cidr, '-m', 'comment', '--comment', 'cls-hotspot-helper-share', '-j', 'MASQUERADE'],
            ['-I', 'FORWARD', '1', '-i', AP, '-s', cidr, '-m', 'comment', '--comment', 'cls-hotspot-helper-share', '-j', 'ACCEPT'],
            ['-I', 'FORWARD', '1', '-o', AP, '-d', cidr, '-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-m', 'comment', '--comment', 'cls-hotspot-helper-share', '-j', 'ACCEPT'],
        ]
        for rule in planned:
            command(['/usr/sbin/iptables', '-w', '3', *rule])
            rules.append(rule)
        control_path = RUNTIME / 'control.sock'
        control_path.unlink(missing_ok=True)
        control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control.bind(str(control_path))
        os.chmod(control_path, 0o600)
        os.chown(control_path, int(os.environ.get('SUDO_UID', '0')), int(os.environ.get('SUDO_GID', '0')))
        control.listen(2)
        control.settimeout(.5)
        save_result(dict(status='AP_ACTIVE_AWAITING_JETSON', ssid=ssid, host_ip=gateway, interface=AP, upstream_profile=temporary, original_profile=original, upstream_ssid=plan['ssid'], frequency_mhz=plan['frequency'], upstream_interface=STA, pid=os.getpid()))
        print('热点已启动：' + ssid + '，本机 ' + gateway + '。通过热点助手面板或 hotspot-helper stop 关闭热点。', flush=True)
        while running:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('热点或 DHCP 服务退出')
            if active_uuid() != temporary:
                raise RuntimeError('上游连接发生变化，停止临时热点')
            try:
                client, _ = control.accept()
                with client:
                    client.settimeout(1)
                    request = client.recv(64).strip()
                    if request == b'stop':
                        running = False
                        client.sendall(b'STOPPING\n')
                    else:
                        client.sendall(b'RUNNING\n')
            except socket.timeout:
                pass
        save_result(dict(status='STOPPED', ssid=ssid))
    except Exception as error:
        save_result(dict(status='FAILED', error=str(error)))
        print('失败：' + str(error), flush=True)
        raise
    finally:
        if control is not None:
            control.close()
            (RUNTIME / 'control.sock').unlink(missing_ok=True)
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        for rule in reversed(rules):
            delete = rule.copy()
            if '-A' in delete:
                delete[delete.index('-A')] = '-D'
            else:
                index = delete.index('-I')
                delete[index:index + 3] = ['-D', 'FORWARD']
            command(['/usr/sbin/iptables', '-w', '3', *delete], False)
        if old_forward == '0':
            Path('/proc/sys/net/ipv4/ip_forward').write_text('0\n')
        if interface_created:
            command(['/usr/sbin/iw', 'dev', AP, 'del'], False)
        (RUNTIME / 'hostapd.conf').unlink(missing_ok=True)
        if conf_created:
            NM_CONF.unlink(missing_ok=True)
            command(['nmcli', 'general', 'reload', 'conf'], False)
        if switched and active_uuid() in (temporary, '', '--'):
            restored = command(['nmcli', '--wait', '25', 'connection', 'up', 'uuid', original, 'ifname', STA], False)
            print('原 Wi-Fi 配置已恢复。' if restored.returncode == 0 else '原 Wi-Fi 自动恢复失败，请在系统网络菜单重新选择原网络。', flush=True)
        if temporary:
            command(['nmcli', 'connection', 'delete', 'uuid', temporary], False)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('已取消。', flush=True)
        sys.exit(130)
    except Exception as error:
        print('未完成：' + str(error), flush=True)
        sys.exit(1)
