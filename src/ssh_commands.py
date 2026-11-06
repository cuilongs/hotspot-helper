"""Remember SSH usernames per device; generate commands without connecting."""
from pathlib import Path
import ipaddress
import json
import os
import re
import stat
import tempfile
from hotspot_common import CONFIG_DIR


USERS_FILE = CONFIG_DIR / 'device_users.json'


def device_key(mac):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac):
        raise ValueError('设备地址格式异常。')
    return mac.lower()


def read_users():
    try:
        fd = os.open(USERS_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 65536:
            raise ValueError('SSH 用户设置的文件格式或所有者异常。')
        users = json.load(stream)
        if not isinstance(users, dict):
            raise ValueError('SSH 用户设置格式异常。')
        return users


def username(mac):
    return read_users().get(device_key(mac), '')


def checked_user(value):
    value = value.strip()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', value):
        raise ValueError('请输入设备的 SSH 登录用户名，例如 nvidia；仅支持字母、数字、下划线、点和短横线。')
    return value


def save_username(mac, value):
    value = checked_user(value)
    users = read_users()
    users[device_key(mac)] = value
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.device_users_', dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(users, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, USERS_FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)


def command(device):
    user = checked_user(username(device['mac']))
    try:
        address = str(ipaddress.IPv4Address(device['ip']))
    except ipaddress.AddressValueError:
        raise ValueError('设备尚未获得可用 IP 地址，请稍后重试。') from None
    return 'ssh ' + user + '@' + address
