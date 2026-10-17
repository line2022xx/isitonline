"""程序入口。

@brief 组装各模块并按依赖顺序启动。
@details 启动顺序：Config.load -> Monitor.start -> ApiServer.start -> GUI 主循环。
    配置文件与日志均写入程序所在目录（打包成 exe 后即 exe 同目录）。
@author linexx
"""

import os
import sys
import tkinter as tk

from api import ApiServer
from config import Config
from eventlog import EventLog
from gui import App
from monitor import Monitor


def base_dir():
    """@brief 返回配置/日志应写入的目录。

    @details 打包为单文件 exe 后，__file__ 指向临时解压目录（_MEIPASS），
        需改用 sys.executable 所在目录，保证配置/日志落在 exe 旁且持久。
    @return str 目录绝对路径
    @author linexx
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    """@brief 程序主流程：初始化各模块并进入 GUI 主循环。

    @author linexx
    """
    base = base_dir()

    config = Config(os.path.join(base, "devices.json"))
    config.load()

    event_log = EventLog(base)

    monitor = Monitor(config, event_log)
    config.set_on_change(monitor.notify_config_changed)
    monitor.start()

    api_server = ApiServer(monitor, config, event_log)
    api_server.start()

    event_log.log("程序启动，监控 %d 个设备" % len(config.snapshot()["devices"]))

    root = tk.Tk()
    App(root, config, monitor, api_server, event_log)
    root.mainloop()

    # 主循环退出后兜底清理（幂等，正常路径已由 on_close 处理）
    api_server.stop()
    monitor.stop()
    event_log.log("程序退出")


if __name__ == "__main__":
    main()
