"""One-time, explicitly requested narrow sudo authorization; root-owned code."""
from pathlib import Path
import argparse
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile

MARKER = '# Managed by Hotspot Helper; only this application start command.\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['enable', 'disable'])
    parser.add_argument('--config')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('设置一次性授权需要本机管理员认证。')
    uid = int(os.environ.get('SUDO_UID', '0'))
    if uid <= 0:
        raise RuntimeError('请从普通用户的热点助手中设置授权。')
    username = pwd.getpwuid(uid).pw_name
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?', username):
        raise RuntimeError('当前用户名格式暂不支持自动配置。')
    rule = Path('/etc/sudoers.d', 'hotspot-helper-' + str(uid))
    profile_dir = Path('/etc/hotspot-helper/users')
    profile = profile_dir / (str(uid) + '.json')
    if rule.exists() and (rule.is_symlink() or not rule.read_text().startswith(MARKER)):
        raise RuntimeError('发现同名自定义授权文件，未覆盖。')
    if args.action == 'disable':
        rule.unlink(missing_ok=True)
        profile.unlink(missing_ok=True)
        print('免重复认证已撤销；以后开启热点会请求管理员认证。', flush=True)
        return
    program = Path('/usr/lib/hotspot-helper/control')
    info = program.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('请先安装正式软件包，再启用此功能。')
    if not args.config:
        raise RuntimeError('缺少个人配置文件。')
    config = Path(args.config).absolute()
    fd = os.open(config, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077 or info.st_size > 16384:
            raise RuntimeError('个人配置须为调用用户拥有、权限 600 的普通文件。')
        json.load(stream)
    profile_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    content = MARKER + username + ' ALL=(root) NOPASSWD: /usr/lib/hotspot-helper/control start\n'
    rule.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.hotspot-helper-', dir=rule.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.chmod(temporary, 0o440)
        result = subprocess.run(['/usr/sbin/visudo', '-cf', temporary], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('授权语法检查失败：' + result.stderr.strip())
        fd, profile_temp = tempfile.mkstemp(prefix='.user-', dir=profile_dir)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(dict(uid=uid, username=username, config=str(config)), stream)
            os.chmod(profile_temp, 0o644)
            os.replace(profile_temp, profile)
        finally:
            Path(profile_temp).unlink(missing_ok=True)
        os.replace(temporary, rule)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('一次性授权已完成，以后启动本助手热点无需再次输入管理员密码。', flush=True)
    print('授权仅允许 /usr/lib/hotspot-helper/control start，可随时撤销。', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('未完成：' + str(error), flush=True)
        sys.exit(1)
