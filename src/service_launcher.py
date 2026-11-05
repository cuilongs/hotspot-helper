"""Start a transient systemd worker after local sudo authentication."""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('worker_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('开启后台热点需要本机认证。')
    if not Path('/run/systemd/system').exists():
        raise RuntimeError('此电脑未运行 systemd，暂不支持该后台模式。')
    uid = int(os.environ.get('SUDO_UID', '0'))
    gid = int(os.environ.get('SUDO_GID', '0'))
    helper = ROOT / 'start_standard_ap.py'
    unit = 'hotspot-helper-' + str(uid) + '.service'
    worker_args = args.worker_args[1:] if args.worker_args[:1] == ['--'] else args.worker_args
    if '--allow-roam' not in worker_args:
        raise RuntimeError('缺少启动授权参数。')
    candidates = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            command = [p.decode() for p in proc.joinpath('cmdline').read_bytes().split(b'\0') if p]
            if len(command) >= 2 and Path(command[0]).name.startswith('python3') and command[1] == str(helper):
                if '/' + unit in proc.joinpath('cgroup').read_text():
                    print('后台服务已在启动或运行。', flush=True)
                    return
                candidates.append((int(proc.name), proc))
        except (OSError, UnicodeError):
            continue
    if candidates:
        state_paths = [Path('/run/cls-hotspot-helper/state.json'), ROOT / 'hotspot_result.json']
        owned = ROOT.stat().st_uid == uid
        for path in state_paths:
            try:
                data = json.loads(path.read_text())
                if data.get('owner_uid') == uid:
                    owned = True
            except (OSError, ValueError):
                pass
        if not owned:
            raise RuntimeError('已有其他用户的热点管理进程，未停止它。')
        print('正在把当前热点交给系统后台管理，期间会短暂重连。', flush=True)
        for pid, _ in candidates:
            try:
                os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            live = False
            for _, proc in candidates:
                try:
                    live |= str(helper).encode() in proc.joinpath('cmdline').read_bytes().split(b'\0')
                except OSError:
                    pass
            if not live:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('原热点尚未完成关闭，请稍后重试。')
    result = subprocess.run([
        '/usr/bin/systemd-run', '--collect', '--unit=' + unit,
        '--description=Hotspot Helper', '--service-type=exec',
        '--property=KillMode=mixed', '--property=TimeoutStopSec=45s',
        '--setenv=SUDO_UID=' + str(uid), '--setenv=SUDO_GID=' + str(gid),
        '/usr/bin/python3', str(helper), *worker_args,
    ], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or '后台服务未启动。')
    print('系统后台服务已提交：' + unit, flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('未完成：' + str(error), flush=True)
        sys.exit(1)
