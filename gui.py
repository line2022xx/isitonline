"""tkinter GUI。

@brief 实时显示设备在线状态，支持增删改设备与服务端参数配置。
@details 状态同步采用 root.after 定时轮询 monitor 的线程安全快照，后台线程不碰 GUI 控件。
    关闭时先停 API、再停监控线程，最后销毁窗口，保证干净退出。
@author linexx
"""

import time
import tkinter as tk
from tkinter import messagebox, ttk

import autostart


class App:
    """主界面。

    @brief 组装设备列表、操作按钮与状态栏，定时刷新设备状态。
    @author linexx
    """

    REFRESH_MS = 1000  # UI 刷新周期（毫秒）

    def __init__(self, root, config, monitor, api_server, event_log):
        """@brief 构建主界面。

        @param root tk 根窗口
        @param config Config 配置对象
        @param monitor Monitor 监控引擎
        @param api_server ApiServer API 服务
        @param event_log EventLog 事件日志
        @author linexx
        """
        self.root = root
        self.config = config
        self.monitor = monitor
        self.api_server = api_server
        self.event_log = event_log

        root.title("服务器在线监控")
        root.geometry("760x430")
        root.minsize(620, 300)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_widgets()
        self._refresh()

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_widgets(self):
        """@brief 构建 Treeview、按钮行与状态栏。

        @author linexx
        """
        columns = ("name", "host", "status", "last_checked", "duration")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")
        self.tree.heading("name", text="设备名称")
        self.tree.heading("host", text="主机/IP")
        self.tree.heading("status", text="状态")
        self.tree.heading("last_checked", text="最后检查")
        self.tree.heading("duration", text="当前状态持续")
        self.tree.column("name", width=170, anchor="w")
        self.tree.column("host", width=170, anchor="w")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("last_checked", width=150, anchor="center")
        self.tree.column("duration", width=120, anchor="center")
        self.tree.tag_configure("online", foreground="#0a7d1f")
        self.tree.tag_configure("offline", foreground="#c0392b")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        scrollbar = ttk.Scrollbar(self.tree, orient="vertical",
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=(8, 4))

        # 按钮行
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(btn_frame, text="新增设备", command=self._add_device).pack(
            side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="编辑", command=self._edit_device).pack(
            side="left", padx=6)
        ttk.Button(btn_frame, text="删除", command=self._delete_device).pack(
            side="left", padx=6)
        ttk.Button(btn_frame, text="立即刷新", command=self._refresh_now).pack(
            side="left", padx=6)
        ttk.Button(btn_frame, text="查看事件日志", command=self._show_events).pack(
            side="left", padx=6)
        # ---ADD---: 服务端参数配置入口
        ttk.Button(btn_frame, text="设置", command=self._open_settings).pack(
            side="right", padx=(6, 0))

        # 状态栏
        self.status_var = tk.StringVar()
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               anchor="w", relief="sunken", padding=(6, 2))
        status_bar.pack(fill="x", side="bottom")

        self.tree.bind("<Double-1>", lambda e: self._edit_device())

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def _refresh(self):
        """@brief 定时刷新入口（after 轮询）。

        @author linexx
        """
        self._refresh_now()
        self.root.after(self.REFRESH_MS, self._refresh)

    def _refresh_now(self):
        """@brief 立即刷新列表与状态栏。

        @author linexx
        """
        self._update_tree()
        self._update_status_bar()

    def _update_tree(self):
        """@brief 用 monitor 状态快照刷新 Treeview，并恢复选中项。

        @author linexx
        """
        selected = self._selected_name()
        self.tree.delete(*self.tree.get_children())
        for s in self.monitor.get_status():
            tag = "online" if s["online"] else "offline"
            self.tree.insert(
                "", "end",
                values=(
                    s["name"],
                    s["host"],
                    "在线" if s["online"] else "离线",
                    self._fmt_time(s["last_checked"]),
                    self._fmt_duration(s["since"]),
                ),
                tags=(tag,),
            )
        # 恢复选中项
        if selected:
            for child in self.tree.get_children():
                if self.tree.item(child)["values"][0] == selected:
                    self.tree.selection_set(child)
                    break

    def _update_status_bar(self):
        """@brief 刷新底部状态栏（设备数、API 状态）。

        @author linexx
        """
        g = self.config.snapshot()["global"]
        total = len(self.monitor.get_status())
        if self.api_server.running:
            api_text = "API: http://%s:%s/api/status" % (
                g["api_host"], g["api_port"])
        else:
            api_text = "API: 未启动"
            if self.api_server.last_error:
                api_text += " (%s)" % self.api_server.last_error
        self.status_var.set("设备数: %d  |  监控运行中  |  %s" % (total, api_text))

    def _selected_name(self):
        """@brief 返回当前选中设备的名称。

        @return str 设备名称，未选中返回 None
        @author linexx
        """
        sel = self.tree.selection()
        if not sel:
            return None
        values = self.tree.item(sel[0])["values"]
        return values[0] if values else None

    # ------------------------------------------------------------------
    # 设备增删改
    # ------------------------------------------------------------------
    def _add_device(self):
        """@brief 弹出新增设备对话框。

        @author linexx
        """
        dialog = _DeviceDialog(self.root, "新增设备")
        self.root.wait_window(dialog.top)
        if not dialog.result:
            return
        name, host = dialog.result
        try:
            self.config.add_device(name, host)
        except ValueError as e:
            messagebox.showerror("错误", str(e))

    def _edit_device(self):
        """@brief 弹出编辑设备对话框。

        @author linexx
        """
        name = self._selected_name()
        if not name:
            messagebox.showinfo("提示", "请先在列表中选择一个设备")
            return
        dev = self.config.get_device(name)
        if not dev:
            return
        dialog = _DeviceDialog(self.root, "编辑设备", name=dev["name"], host=dev["host"])
        self.root.wait_window(dialog.top)
        if not dialog.result:
            return
        new_name, new_host = dialog.result
        try:
            self.config.rename_device(name, new_name, new_host)
        except ValueError as e:
            messagebox.showerror("错误", str(e))

    def _delete_device(self):
        """@brief 删除选中设备（二次确认）。

        @author linexx
        """
        name = self._selected_name()
        if not name:
            messagebox.showinfo("提示", "请先在列表中选择一个设备")
            return
        if not messagebox.askyesno("确认", "确定删除设备「%s」？" % name):
            return
        try:
            self.config.remove_device(name)
        except ValueError as e:
            messagebox.showerror("错误", str(e))

    def _show_events(self):
        """@brief 弹出窗口展示最近上下线事件。

        @author linexx
        """
        events = self.event_log.get_recent(100)
        win = tk.Toplevel(self.root)
        win.title("最近上下线事件")
        win.geometry("680x360")
        win.transient(self.root)
        txt = tk.Text(win, wrap="none")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        if not events:
            txt.insert("end", "（暂无事件）")
        for e in events:
            txt.insert("end", "%s  %-4s  %-20s  %s\n" % (
                e["time_str"], e["event"].upper(), e["name"], e["host"]))
        txt.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 6))

    # ---ADD---: 服务端参数配置（本次新增）
    def _open_settings(self):
        """@brief 弹出服务端设置对话框并应用配置。

        @details ping 相关参数经热加载立即生效；API 地址/端口变化则重启 API 服务；
            开机自启写入/删除注册表 Run 键。
        @author linexx
        """
        g = self.config.snapshot()["global"]
        dialog = _SettingsDialog(self.root, g, autostart.is_enabled())
        self.root.wait_window(dialog.top)
        if not dialog.result:
            return
        new = dict(dialog.result)
        autostart_on = new.pop("autostart")
        # ---ADD---: 应用开机自启开关
        try:
            if autostart_on:
                autostart.enable()
            else:
                autostart.disable()
        except OSError as e:
            messagebox.showerror("错误", "开机自启设置失败：%s" % e)
        api_changed = (
            str(new["api_host"]) != str(g["api_host"])
            or int(new["api_port"]) != int(g["api_port"])
        )
        self.config.update_global(**new)
        if api_changed:
            ok = self.api_server.restart()
            if not ok:
                messagebox.showerror(
                    "错误",
                    "API 重启失败，请检查端口是否被占用。\n%s"
                    % (self.api_server.last_error or ""))
            else:
                messagebox.showinfo("提示", "设置已保存，API 已重启")
        else:
            messagebox.showinfo("提示", "设置已保存")
        self._refresh_now()

    # ------------------------------------------------------------------
    # 优雅退出
    # ------------------------------------------------------------------
    def on_close(self):
        """@brief 关闭窗口前依次停 API、停监控线程、销毁窗口。

        @author linexx
        """
        try:
            self.api_server.stop()
        finally:
            self.monitor.stop()
            self.root.destroy()

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_time(ts):
        """@brief 格式化时间戳为可读时间。

        @param ts 时间戳（秒）
        @return str 时间字符串
        @author linexx
        """
        if not ts:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    @staticmethod
    def _fmt_duration(since):
        """@brief 格式化状态持续时长为 HH:MM:SS（超一天显示天）。

        @param since 状态起始时间戳（秒）
        @return str 时长字符串
        @author linexx
        """
        if not since:
            return "-"
        secs = int(time.time() - since)
        if secs < 0:
            secs = 0
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        if d:
            return "%d天 %02d:%02d:%02d" % (d, h, m, s)
        return "%02d:%02d:%02d" % (h, m, s)


class _DeviceDialog:
    """设备输入对话框。

    @brief 新增/编辑设备的名称与主机/IP 输入框。result 为 (name, host) 或 None。
    @author linexx
    """

    def __init__(self, parent, title, name="", host=""):
        """@brief 构建输入对话框。

        @param parent 父窗口
        @param title 对话框标题
        @param name 初始设备名（编辑时）
        @param host 初始主机/IP（编辑时）
        @author linexx
        """
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)

        frame = ttk.Frame(self.top, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="设备名称:").grid(
            row=0, column=0, padx=6, pady=6, sticky="e")
        self.name_var = tk.StringVar(value=name)
        self.name_entry = ttk.Entry(frame, textvariable=self.name_var, width=28)
        self.name_entry.grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(frame, text="主机/IP:").grid(
            row=1, column=0, padx=6, pady=6, sticky="e")
        self.host_var = tk.StringVar(value=host)
        self.host_entry = ttk.Entry(frame, textvariable=self.host_var, width=28)
        self.host_entry.grid(row=1, column=1, padx=6, pady=6)

        btn = ttk.Frame(frame)
        btn.grid(row=2, column=0, columnspan=2, pady=(8, 0))
        ttk.Button(btn, text="确定", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btn, text="取消", command=self._cancel).pack(side="left", padx=6)

        self.top.bind("<Return>", lambda e: self._ok())
        self.top.bind("<Escape>", lambda e: self._cancel())
        self.top.protocol("WM_DELETE_WINDOW", self._cancel)
        self.name_entry.focus_set()

    def _ok(self):
        """@brief 校验并提交结果。

        @author linexx
        """
        name = self.name_var.get().strip()
        host = self.host_var.get().strip()
        if not name or not host:
            messagebox.showwarning("提示", "名称和主机/IP 都不能为空", parent=self.top)
            return
        self.result = (name, host)
        self.top.destroy()

    def _cancel(self):
        """@brief 取消并关闭。

        @author linexx
        """
        self.result = None
        self.top.destroy()


class _SettingsDialog:
    """服务端设置对话框。

    @brief 配置轮询/防抖/API 监听等服务端参数。result 为 dict 或 None。
    @author linexx
    """

    # 字段定义：(key, 标签)
    _FIELDS = [
        ("ping_interval", "轮询间隔(秒)"),
        ("ping_timeout", "Ping超时(毫秒)"),
        ("fail_threshold", "防抖阈值(次)"),
        ("api_host", "API监听地址"),
        ("api_port", "API监听端口"),
    ]

    def __init__(self, parent, g, autostart_enabled=False):
        """@brief 构建设置对话框，预填当前配置。

        @param parent 父窗口
        @param g 当前 global 配置字典
        @param autostart_enabled 当前开机自启状态
        @author linexx
        """
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("服务端设置")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)

        frame = ttk.Frame(self.top, padding=12)
        frame.pack(fill="both", expand=True)

        self.vars = {}
        for i, (key, label) in enumerate(self._FIELDS):
            ttk.Label(frame, text=label + ":").grid(
                row=i, column=0, padx=6, pady=5, sticky="e")
            self.vars[key] = tk.StringVar(value=str(g.get(key, "")))
            ttk.Entry(frame, textvariable=self.vars[key], width=24).grid(
                row=i, column=1, padx=6, pady=5)

        # ---ADD---: 开机自启开关
        self.autostart_var = tk.BooleanVar(value=autostart_enabled)
        ttk.Checkbutton(
            frame, text="开机自启（用户登录后自动运行）",
            variable=self.autostart_var).grid(
            row=len(self._FIELDS), column=0, columnspan=2, pady=(8, 0), sticky="w")

        btn = ttk.Frame(frame)
        btn.grid(row=len(self._FIELDS) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn, text="确定", command=self._ok).pack(side="left", padx=6)
        ttk.Button(btn, text="取消", command=self._cancel).pack(side="left", padx=6)

        self.top.bind("<Return>", lambda e: self._ok())
        self.top.bind("<Escape>", lambda e: self._cancel())
        self.top.protocol("WM_DELETE_WINDOW", self._cancel)

    def _ok(self):
        """@brief 校验并提交设置。

        @author linexx
        """
        try:
            interval = int(self.vars["ping_interval"].get())
            timeout = int(self.vars["ping_timeout"].get())
            threshold = int(self.vars["fail_threshold"].get())
            port = int(self.vars["api_port"].get())
        except ValueError:
            messagebox.showwarning("提示", "数值字段必须为整数", parent=self.top)
            return

        host = self.vars["api_host"].get().strip()
        if not host:
            messagebox.showwarning("提示", "API 监听地址不能为空", parent=self.top)
            return
        if interval < 1 or timeout < 100 or threshold < 1:
            messagebox.showwarning(
                "提示", "轮询间隔>=1、Ping超时>=100、防抖阈值>=1", parent=self.top)
            return
        if not (1 <= port <= 65535):
            messagebox.showwarning("提示", "端口必须在 1-65535 之间", parent=self.top)
            return

        self.result = {
            "ping_interval": interval,
            "ping_timeout": timeout,
            "fail_threshold": threshold,
            "api_host": host,
            "api_port": port,
            "autostart": bool(self.autostart_var.get()),
        }
        self.top.destroy()

    def _cancel(self):
        """@brief 取消并关闭。

        @author linexx
        """
        self.result = None
        self.top.destroy()
