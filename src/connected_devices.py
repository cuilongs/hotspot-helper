"""Current clients come from the AP station table, not historical DHCP leases."""
from pathlib import Path
import json
import os
import re
import subprocess
import time


def clients(interface='hotspotap0', runtime=Path('/run/cls-hotspot-helper')):
    try:
        result = subprocess.run(['/usr/sbin/iw', 'dev', interface, 'station', 'dump'], capture_output=True, text=True, timeout=3, env=dict(os.environ, LC_ALL='C'))
        if result.returncode:
            return [], '暂时无法读取当前连接状态。'
    except (OSError, subprocess.TimeoutExpired):
        return [], '暂时无法读取当前连接状态。'
    leases = {}
    try:
        for line in (runtime / 'dhcp/leases').read_text(errors='replace').splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].isdigit() and (int(parts[0]) == 0 or int(parts[0]) > time.time()):
                leases[parts[1].lower()] = dict(ip=parts[2], name=parts[3] if parts[3] != '*' else '未提供设备名')
    except OSError:
        pass
    neighbors = {}
    try:
        result_neighbors = subprocess.run(['/usr/sbin/ip', '-j', '-4', 'neighbor', 'show', 'dev', interface], capture_output=True, text=True, timeout=2)
        if result_neighbors.returncode == 0:
            neighbors = {entry['lladdr'].lower(): entry['dst'] for entry in json.loads(result_neighbors.stdout) if 'lladdr' in entry and 'dst' in entry}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    devices = []
    sections = re.split(r'^Station\s+([0-9a-f:]{17})\s+.*$', result.stdout, flags=re.M | re.I)
    for index in range(1, len(sections), 2):
        mac, details = sections[index].lower(), sections[index + 1]
        if re.search(r'^\s*(?:authorized|associated|authenticated):\s*no\s*$', details, re.M):
            continue
        metadata = leases.get(mac, {})
        signal = re.search(r'^\s*signal:\s*(-?\d+)', details, re.M)
        duration = re.search(r'^\s*connected time:\s*(\d+)', details, re.M)
        devices.append(dict(mac=mac, name=metadata.get('name', '未提供设备名'), ip=neighbors.get(mac, metadata.get('ip', '正在获取地址')), signal_dbm=int(signal[1]) if signal else None, connected_seconds=int(duration[1]) if duration else None))
    return sorted(devices, key=lambda device: (device['name'], device['mac'])), None
