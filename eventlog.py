"""事件日志模块。

@brief 上下线事件持久化 + 内存环形缓冲 + logging 配置。
@details
    - events 日志：按天轮转，每行记录一次上下线事件。
    - app 日志：记录程序运行信息（启动/停止/端口占用等）。
    - 内存环形缓冲：供 HTTP API 查询最近事件，deque(maxlen) 防长期运行内存泄漏。
@author linexx
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from collections import deque


class EventLog:
    """事件日志。

    @brief 统一管理上下线事件日志与程序运行日志，并提供内存事件查询。
    @author linexx
    """

    def __init__(self, base_dir, max_entries=10000):
        """@brief 构造并初始化 logging。

        @param base_dir 日志根目录（logs 子目录创建于此）
        @param max_entries 内存环形缓冲最大条目数
        @author linexx
        """
        self._lock = threading.RLock()
        self._events = deque(maxlen=max_entries)
        self._events_logger = None
        self._setup_logging(base_dir)

    # ------------------------------------------------------------------
    # logging 初始化（只配置一次，幂等）
    # ------------------------------------------------------------------
    def _setup_logging(self, base_dir):
        """@brief 初始化 events / app 两个 logger 的 handler。

        @param base_dir 日志根目录
        @author linexx
        """
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)

        # 上下线事件日志
        events_logger = logging.getLogger("events")
        events_logger.setLevel(logging.INFO)
        events_logger.propagate = False
        if not events_logger.handlers:
            eh = logging.handlers.TimedRotatingFileHandler(
                os.path.join(log_dir, "events.log"),
                when="midnight", backupCount=30, encoding="utf-8")
            eh.setFormatter(logging.Formatter(
                "%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            events_logger.addHandler(eh)
        self._events_logger = events_logger

        # 应用运行日志
        app_logger = logging.getLogger("app")
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False
        if not app_logger.handlers:
            ah = logging.handlers.TimedRotatingFileHandler(
                os.path.join(log_dir, "app.log"),
                when="midnight", backupCount=30, encoding="utf-8")
            ah.setFormatter(logging.Formatter(
                "%(asctime)s  [%(levelname)s]  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"))
            app_logger.addHandler(ah)
            # 源码运行时额外输出到控制台（windowed exe 下 sys.stderr 为 None，自动跳过）
            if sys.stderr is not None:
                sh = logging.StreamHandler()
                sh.setFormatter(logging.Formatter(
                    "%(asctime)s  [%(levelname)s]  %(message)s",
                    datefmt="%H:%M:%S"))
                app_logger.addHandler(sh)
        self._app_logger = app_logger

    def log(self, message, level="info"):
        """@brief 写应用运行日志。

        @param message 日志内容
        @param level 日志级别（info/warning/error 等）
        @author linexx
        """
        logger = getattr(self, "_app_logger", None)
        if logger is not None:
            getattr(logger, level, logger.info)(message)

    # ------------------------------------------------------------------
    # 上下线事件
    # ------------------------------------------------------------------
    def record(self, name, host, event, ts=None):
        """@brief 记录一次上下线事件。

        @param name 设备名称
        @param host 主机名或 IP 地址
        @param event 事件类型，'up' 或 'down'
        @param ts 时间戳（默认当前时间）
        @author linexx
        """
        if ts is None:
            ts = time.time()
        entry = {
            "time": ts,
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "event": event,
            "name": name,
            "host": host,
        }
        with self._lock:
            self._events.append(entry)

        if self._events_logger is not None:
            self._events_logger.info("%-4s  %-20s  %s", event.upper(), name, host)

    def get_recent(self, n=100):
        """@brief 返回最近 n 条事件（时间倒序）。

        @param n 事件条数
        @return list 事件字典列表
        @author linexx
        """
        with self._lock:
            items = list(self._events)
        return list(reversed(items[-n:]))
