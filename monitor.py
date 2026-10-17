"""监控引擎。

@brief 后台线程周期 ping，维护设备状态缓存，裁决上下线事件。
@details
    - ping 通过 subprocess 调用系统 ping 命令（Windows 下 -n 1 -w <ms>）。
    - CREATE_NO_WINDOW 隐藏子进程控制台；subprocess.run(timeout) 兜底防卡死。
    - 失败侧 fail_threshold 次连续失败才判定离线（防抖动）；上线侧 1 次成功即上线。
    - 状态缓存用 RLock 保护，对外查询返回深拷贝，供 GUI / API 线程安全读取。
@author linexx
"""

import subprocess
import threading
import time
from dataclasses import dataclass

# Windows 专属；非 Windows 平台回退为 0（本程序目标为 Windows）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class DeviceState:
    """单个设备的内部运行状态。

    @brief 记录在线状态、连续失败计数与时间信息。
    @author linexx
    """

    name: str
    host: str
    online: bool = False
    consecutive_fails: int = 0
    last_checked: float = 0.0
    since: float = 0.0


class Monitor:
    """监控引擎。

    @brief 后台线程周期 ping 各设备，维护状态并记录上下线事件。
    @author linexx
    """

    def __init__(self, config, event_log):
        """@brief 构造监控引擎。

        @param config Config 配置对象
        @param event_log EventLog 事件日志对象
        @author linexx
        """
        self._config = config
        self._event_log = event_log
        self._lock = threading.RLock()
        self._states = {}  # name -> DeviceState
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        """@brief 启动后台监控线程（幂等）。

        @author linexx
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._rebuild_states(self._config.snapshot())
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="monitor")
        self._thread.start()

    def stop(self):
        """@brief 停止监控线程，等待其退出（最多 5 秒）。

        @author linexx
        """
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def notify_config_changed(self):
        """@brief 配置变更后由 Config 回调，立即唤醒轮询线程免等 interval。

        @author linexx
        """
        self._wake_event.set()

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def _run_loop(self):
        """@brief 轮询主循环：每轮快照配置 -> 重建状态 -> 逐个 ping -> 等待间隔。

        @author linexx
        """
        while not self._stop_event.is_set():
            snapshot = self._config.snapshot()
            g = snapshot["global"]
            interval = max(1, int(g.get("ping_interval", 5)))
            timeout_ms = max(100, int(g.get("ping_timeout", 2000)))
            fail_threshold = max(1, int(g.get("fail_threshold", 3)))
            devices = snapshot["devices"]

            self._rebuild_states(snapshot)

            for dev in devices:
                if self._stop_event.is_set():
                    break
                ok = self._ping_once(dev["host"], timeout_ms)
                self._apply_result(dev["name"], dev["host"], ok, fail_threshold)

            self._wake_event.wait(timeout=interval)
            self._wake_event.clear()

    def _ping_once(self, host, timeout_ms):
        """@brief 执行一次 ping，成功返回 True。

        @param host 主机名或 IP 地址
        @param timeout_ms ping 超时（毫秒）
        @return bool ping 成功为 True
        @author linexx
        """
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=(timeout_ms / 1000.0) + 1.0,
                creationflags=CREATE_NO_WINDOW,
            )
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _apply_result(self, name, host, ok, fail_threshold):
        """@brief 应用一次 ping 结果，裁决上下线并记录事件。

        @param name 设备名称
        @param host 主机名或 IP 地址
        @param ok ping 是否成功
        @param fail_threshold 连续失败判定离线的阈值
        @author linexx
        """
        now = time.time()
        to_record = None
        with self._lock:
            st = self._states.get(name)
            if st is None:
                return
            st.last_checked = now
            if ok:
                st.consecutive_fails = 0
                if not st.online:
                    st.online = True
                    st.since = now
                    to_record = ("up", now)
            else:
                st.consecutive_fails += 1
                if st.online and st.consecutive_fails >= fail_threshold:
                    st.online = False
                    st.since = now
                    to_record = ("down", now)
        # 事件日志在锁外写，避免长时间持锁
        if to_record is not None:
            self._event_log.record(name, host, to_record[0], to_record[1])

    def _rebuild_states(self, snapshot):
        """@brief 依据最新配置同步状态表：增删设备、更新 host，保留已有状态。

        @param snapshot 配置快照
        @author linexx
        """
        devices = snapshot["devices"]
        now = time.time()
        with self._lock:
            valid_names = {d["name"] for d in devices}
            for name in list(self._states.keys()):
                if name not in valid_names:
                    del self._states[name]
            for d in devices:
                name, host = d["name"], d["host"]
                st = self._states.get(name)
                if st is None:
                    self._states[name] = DeviceState(
                        name=name, host=host, since=now)
                elif st.host != host:
                    st.host = host

    # ------------------------------------------------------------------
    # 只读查询（供 GUI / API）
    # ------------------------------------------------------------------
    def get_status(self):
        """@brief 返回所有设备状态快照列表（按名称排序）。

        @return list 设备状态字典列表（name/host/online/last_checked/since）
        @author linexx
        """
        result = []
        with self._lock:
            for st in self._states.values():
                result.append({
                    "name": st.name,
                    "host": st.host,
                    "online": st.online,
                    "last_checked": st.last_checked,
                    "since": st.since,
                })
        result.sort(key=lambda x: x["name"])
        return result

    def get_one(self, name):
        """@brief 返回单个设备状态快照。

        @param name 设备名称
        @return dict 设备状态，不存在返回 None
        @author linexx
        """
        with self._lock:
            st = self._states.get(name)
            if st is None:
                return None
            return {
                "name": st.name,
                "host": st.host,
                "online": st.online,
                "last_checked": st.last_checked,
                "since": st.since,
            }
