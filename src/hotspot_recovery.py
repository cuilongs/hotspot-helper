"""Recover only this helper's orphaned AP while its global lock is held."""
from pathlib import Path
import os
import shlex
import signal
import stat
import time


def recover(runtime, interface, nm_conf, rule_tag, command):
    runtime, nm_conf = Path(runtime), Path(nm_conf)
    interface_exists = Path('/sys/class/net', interface).exists()
    if not interface_exists and not nm_conf.exists():
        return False
    # Never infer ownership from an interface name alone.
    if not nm_conf.exists() or nm_conf.is_symlink():
        raise RuntimeError('发现同名接口，但缺少本助手的配置标记；未清理，请返回聊天处理。')
    info = nm_conf.stat()
    content = nm_conf.read_text()
    if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or 'match-device=interface-name:' + interface not in content or 'managed=0' not in content:
        raise RuntimeError('临时网络配置无法确认属于本助手，未清理。')
    if interface_exists:
        description = command(['/usr/sbin/iw', 'dev', interface, 'info'], False).stdout
        if 'type AP' not in description:
            raise RuntimeError('同名接口并非 AP，未清理。')
    print('发现助手退出后遗留的热点，正在回收本次服务和临时设置。', flush=True)
    candidates = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = proc.joinpath('cmdline').read_bytes().split(b'\0')
            args = [a.decode(errors='replace') for a in args if a]
            if not args:
                continue
            executable = Path(args[0]).name
            hostapd = executable == 'hostapd' and str(runtime / 'hostapd.conf') in args
            dnsmasq = executable == 'dnsmasq' and '--interface=' + interface in args and '--dhcp-leasefile=' + str(runtime / 'dhcp/leases') in args
            if hostapd or dnsmasq:
                started = proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]
                candidates.append((int(proc.name), proc, started))
        except (OSError, IndexError):
            continue

    def same_process(proc, started):
        try:
            return proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19] == started
        except (OSError, IndexError):
            return False

    for pid, proc, started in candidates:
        if same_process(proc, started):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(same_process(proc, started) for _, proc, started in candidates):
        time.sleep(.1)
    for pid, proc, started in candidates:
        if same_process(proc, started):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    for table, chain in [('filter', 'FORWARD'), ('nat', 'POSTROUTING')]:
        listing = command(['/usr/sbin/iptables', '-w', '3', '-t', table, '-S', chain])
        for line in listing.stdout.splitlines():
            parts = shlex.split(line)
            if '--comment' not in parts or parts[parts.index('--comment') + 1] != rule_tag:
                continue
            if table == 'filter' and interface not in parts:
                continue
            if parts[:2] != ['-A', chain]:
                continue
            command(['/usr/sbin/iptables', '-w', '3', '-t', table, '-D', *parts[1:]])
    if interface_exists:
        command(['/usr/sbin/iw', 'dev', interface, 'del'])
    nm_conf.unlink()
    command(['nmcli', 'general', 'reload', 'conf'])
    for name in ['hostapd.conf', 'control.sock', 'dnsmasq.pid']:
        (runtime / name).unlink(missing_ok=True)
    # Forwarding's original value is unknown after an unjournaled old session;
    # leave that global setting alone rather than guessing across other services.
    print('遗留热点已回收。', flush=True)
    return True
