"""开机自启管理。

@brief 通过注册表 Run 键实现用户登录后自动启动。
@details 使用 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run，
    无需管理员权限。源码运行以 pythonw.exe 无控制台启动，打包后以 exe 启动。
@author linexx
"""

import os
import sys
import winreg

# 注册表 Run 键路径（当前用户，登录后自启）
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "IsItOnline"


def _command():
    """@brief 构造自启动命令行。

    @return str 自启动要执行的命令行
    @author linexx
    """
    if getattr(sys, "frozen", False):
        # 打包后直接指向 exe
        return '"%s"' % sys.executable
    # 源码运行：用 pythonw.exe 无控制台启动 main.py
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return '"%s" "%s"' % (pythonw, main_path)


def is_enabled():
    """@brief 查询开机自启是否已启用。

    @return bool True 表示已启用
    @author linexx
    """
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def enable():
    """@brief 启用开机自启（幂等，重复调用覆盖原值）。

    @raise OSError 注册表写入失败时抛出
    @author linexx
    """
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _command())


def disable():
    """@brief 禁用开机自启（键不存在时静默忽略）。

    @author linexx
    """
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _APP_NAME)
    except (FileNotFoundError, OSError):
        pass
