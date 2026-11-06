"""Small native GTK4 hotspot control panel; network privileges stay in helper."""
import subprocess
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from hotspot_common import ROOT, SOCKET, secret, state, stop, save_password, save_ssid, terminal_command, quick_enabled


class HotspotApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.robotics.HotspotHelper')
        self.password_window = None
        self.name_window = None
        self.start_pending = None

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='热点助手')
        self.window.set_default_size(580, 740)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for setter in ('set_margin_top', 'set_margin_bottom', 'set_margin_start', 'set_margin_end'):
            getattr(box, setter)(24)
        main_scroll = Gtk.ScrolledWindow()
        main_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main_scroll.set_child(box)
        self.window.set_child(main_scroll)
        title = Gtk.Label(label='热点助手', xalign=0)
        title.add_css_class('title-1')
        box.append(title)
        description = Gtk.Label(label='本机继续使用 Wi-Fi，同时为其他设备提供热点。', xalign=0)
        description.set_wrap(True)
        box.append(description)
        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class('title-3')
        box.append(self.status)
        self.wifi = Gtk.Label(xalign=0, selectable=True)
        self.wifi.set_wrap(True)
        box.append(self.wifi)
        name_row = Gtk.Box(spacing=12)
        self.name_label = Gtk.Label(label='热点名称：' + secret()['ssid'], xalign=0, selectable=True, hexpand=True)
        name_row.append(self.name_label)
        rename = Gtk.Button(label='修改名称')
        rename.connect('clicked', self.change_name)
        name_row.append(rename)
        box.append(name_row)
        row = Gtk.Box(spacing=12)
        row.append(Gtk.Label(label='热点密码'))
        self.password = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        self.password.set_text(secret()['password'])
        self.password.set_editable(False)
        row.append(self.password)
        change = Gtk.Button(label='修改密码')
        change.connect('clicked', self.change_password)
        row.append(change)
        box.append(row)
        actions = Gtk.Box(spacing=12, homogeneous=True)
        self.start_button = Gtk.Button(label='开启热点')
        self.start_button.add_css_class('suggested-action')
        self.start_button.connect('clicked', self.start_hotspot)
        actions.append(self.start_button)
        self.stop_button = Gtk.Button(label='关闭热点')
        self.stop_button.connect('clicked', self.stop_hotspot)
        actions.append(self.stop_button)
        box.append(actions)
        self.quick_button = Gtk.Button(label='一次性授权：以后开启不再输密码')
        self.quick_button.connect('clicked', self.configure_quick)
        box.append(self.quick_button)
        self.devices_title = Gtk.Label(label='当前已连接设备', xalign=0)
        self.devices_title.add_css_class('heading')
        box.append(self.devices_title)
        self.devices_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.devices_list.add_css_class('boxed-list')
        devices_scroll = Gtk.ScrolledWindow()
        devices_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        devices_scroll.set_min_content_height(52)
        devices_scroll.set_max_content_height(180)
        devices_scroll.set_propagate_natural_height(True)
        devices_scroll.set_child(self.devices_list)
        box.append(devices_scroll)
        self.message = Gtk.Label(xalign=0)
        self.message.set_wrap(True)
        box.append(self.message)
        note = Gtk.Label(label='先连接 Wi-Fi，再开启热点。需要当前网络有可用的 2.4 GHz 接入点。启动成功后可关闭认证终端和本面板，热点继续后台运行。', xalign=0)
        note.set_wrap(True)
        note.add_css_class('dim-label')
        box.append(note)
        command = Gtk.Label(label='命令：hotspot-helper start / stop / status / password', xalign=0, selectable=True)
        command.set_wrap(True)
        command.add_css_class('dim-label')
        box.append(command)
        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)
        self.window.present()

    def terminal(self, action):
        subprocess.Popen(terminal_command(action))

    def refresh(self):
        try:
            current = state()
            self.name_label.set_text('热点名称：' + secret()['ssid'])
            self.status.set_text('◐ 检测到遗留热点，点击开启可恢复' if current.get('needs_recovery') else (('● 热点已在后台运行' if current.get('background') else '● 热点已开启（终端模式）') if current['active'] else '○ 热点未开启'))
            self.wifi.set_text('当前 Wi-Fi：' + current['upstream'] + ('\n本机热点地址：' + str(current['host_ip']) if current['active'] else ''))
            self.start_button.set_sensitive(self.start_pending is None and (not current['active'] or not current.get('background')))
            self.quick_button.set_label('已启用免重复认证（点击可撤销）' if quick_enabled() else '一次性授权：以后开启不再输密码')
            self.start_button.set_label('转为后台运行' if current['active'] and not current.get('background') else '开启热点')
            self.stop_button.set_sensitive(current['active'] or current.get('needs_recovery', False))
            self.show_devices(current)
            if current['last_error'] and not current['active']:
                self.message.set_text(current['last_error'])
        except Exception as error:
            self.message.set_text(str(error))
        return True

    def show_devices(self, current):
        child = self.devices_list.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.devices_list.remove(child)
            child = following
        count = current.get('connected_count')
        self.devices_title.set_text('当前已连接设备' + (' · ' + str(count) + ' 台' if count is not None else ''))
        if not current['active'] or current.get('devices_error') or not current['devices']:
            text = '热点尚未开启' if not current['active'] else (current.get('devices_error') or '暂无设备连接')
            label = Gtk.Label(label=text, xalign=0)
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            label.set_margin_start(12)
            self.devices_list.append(label)
            return
        for device in current['devices']:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            for setter in ('set_margin_top', 'set_margin_bottom', 'set_margin_start', 'set_margin_end'):
                getattr(row, setter)(12)
            top = Gtk.Box(spacing=12)
            name = Gtk.Label(label=device['name'], xalign=0, hexpand=True, selectable=True)
            name.add_css_class('heading')
            name.set_wrap(True)
            top.append(name)
            top.append(Gtk.Label(label=device['ip'], selectable=True))
            row.append(top)
            detail = 'MAC：' + device['mac']
            if device.get('signal_dbm') is not None:
                detail += '    信号：' + str(device['signal_dbm']) + ' dBm'
            label = Gtk.Label(label=detail, xalign=0, selectable=True)
            label.add_css_class('dim-label')
            label.set_wrap(True)
            row.append(label)
            self.devices_list.append(row)

    def start_hotspot(self, *_):
        try:
            if quick_enabled():
                self.message.set_text('正在后台开启热点，无需重复认证。')
                self.start_pending = subprocess.Popen(['/usr/bin/python3', str(ROOT / 'hotspot_cli.py'), 'start'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.start_button.set_sensitive(False)
                GLib.timeout_add(200, self.start_finished)
            else:
                self.message.set_text('已打开本机认证窗口。也可通过一次性授权免去以后的重复认证。')
                self.terminal('start')
        except Exception as error:
            self.start_pending = None
            self.message.set_text(str(error))

    def start_finished(self):
        if self.start_pending is None or self.start_pending.poll() is None:
            return self.start_pending is not None
        output, _ = self.start_pending.communicate()
        self.start_pending = None
        self.message.set_text(output.strip())
        self.refresh()
        return False

    def configure_quick(self, *_):
        try:
            self.terminal('disable-quick-start' if quick_enabled() else 'enable-quick-start')
            self.message.set_text('请在设置窗口完成一次管理员认证；授权仅覆盖本助手启动命令。')
        except Exception as error:
            self.message.set_text(str(error))

    def stop_hotspot(self, *_):
        try:
            if SOCKET.exists():
                self.message.set_text(stop())
            else:
                self.message.set_text('正在打开认证窗口回收遗留热点。')
                self.terminal('stop')
        except Exception as error:
            self.message.set_text(str(error))

    def change_password(self, *_):
        if state()['active']:
            self.message.set_text('请先关闭热点，再修改密码。')
            return
        if self.password_window:
            self.password_window.present()
            return
        window = Gtk.Window(title='修改热点密码', transient_for=self.window, modal=True)
        self.password_window = window
        window.set_default_size(400, 230)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for setter in ('set_margin_top', 'set_margin_bottom', 'set_margin_start', 'set_margin_end'):
            getattr(box, setter)(20)
        window.set_child(box)
        box.append(Gtk.Label(label='输入 8～63 位英文字母、数字或符号。', xalign=0))
        first = Gtk.PasswordEntry(show_peek_icon=True)
        second = Gtk.PasswordEntry(show_peek_icon=True)
        box.append(Gtk.Label(label='新密码', xalign=0))
        box.append(first)
        box.append(Gtk.Label(label='再次输入', xalign=0))
        box.append(second)
        feedback = Gtk.Label(xalign=0)
        feedback.set_wrap(True)
        box.append(feedback)
        save = Gtk.Button(label='保存密码')
        save.add_css_class('suggested-action')
        box.append(save)

        def closed(*_):
            self.password_window = None
            return False

        def commit(*_):
            try:
                save_password(first.get_text(), second.get_text())
                self.password.set_text(secret()['password'])
                self.message.set_text('密码已修改。重新开启热点，并在 客户端设备 上更新已保存的 Wi-Fi 密码。')
                window.close()
            except Exception as error:
                feedback.set_text(str(error))

        window.connect('close-request', closed)
        save.connect('clicked', commit)
        window.present()

    def change_name(self, *_):
        if state()['active'] or self.start_pending is not None:
            self.message.set_text('请先关闭热点，再修改名称。保存后重新开启即可生效。')
            return
        if self.name_window:
            self.name_window.present()
            return
        window = Gtk.Window(title='修改热点名称', transient_for=self.window, modal=True)
        self.name_window = window
        window.set_default_size(420, 200)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for setter in ('set_margin_top', 'set_margin_bottom', 'set_margin_start', 'set_margin_end'):
            getattr(box, setter)(20)
        window.set_child(box)
        box.append(Gtk.Label(label='新名称（支持中文，中文一般不超过 10 个字）', xalign=0))
        entry = Gtk.Entry(text=secret()['ssid'])
        entry.set_activates_default(True)
        box.append(entry)
        feedback = Gtk.Label(xalign=0)
        feedback.set_wrap(True)
        box.append(feedback)
        save = Gtk.Button(label='保存名称')
        save.add_css_class('suggested-action')
        box.append(save)
        window.set_default_widget(save)

        def closed(*_):
            self.name_window = None
            return False

        def commit(*_):
            try:
                save_ssid(entry.get_text())
                self.name_label.set_text('热点名称：' + secret()['ssid'])
                self.message.set_text('名称已保存。重新开启热点后，其他设备需选择新名称连接。')
                window.close()
            except Exception as error:
                feedback.set_text(str(error))

        save.connect('clicked', commit)
        window.connect('close-request', closed)
        window.present()


def main():
    return HotspotApp().run([sys.argv[0]])


if __name__ == '__main__':
    sys.exit(main())
