"""配置管理模块。

@brief 负责 devices.json 的读写、原子写、热加载与变更订阅。
@details 仅使用 Python 标准库，便于离线部署。设备名作为唯一主键。
@author linexx
"""

import copy
import json
import os
import threading

# 默认配置，load 时会用它补齐缺失字段；所有默认值唯一在此定义，避免散落硬编码
DEFAULT_CONFIG = {
    "global": {
        "ping_interval": 5,        # 秒，轮询间隔
        "ping_timeout": 2000,      # 毫秒，ping -w 超时
        "fail_threshold": 3,       # 连续 N 次失败判定离线（防抖动）
        "api_host": "127.0.0.1",   # REST API 监听地址（0.0.0.0 允许外部访问）
        "api_port": 8080,          # REST API 监听端口
    },
    "devices": [
        # { "name": "核心服务器", "host": "192.168.1.10" }
    ],
}


class Config:
    """线程安全的配置存储。

    @brief 提供配置的加载、保存、变更与订阅，设备名作为唯一主键。
    @author linexx
    """

    def __init__(self, path):
        """@brief 构造配置对象。

        @param path 配置文件路径（devices.json）
        @author linexx
        """
        self._path = path
        self._lock = threading.RLock()
        self._on_change = None
        self._data = copy.deepcopy(DEFAULT_CONFIG)

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def load(self):
        """@brief 从磁盘加载配置，缺失/损坏时回退默认值并补齐缺失字段。

        @return self，支持链式调用
        @author linexx
        """
        data = None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = None

        if not isinstance(data, dict):
            data = {}

        with self._lock:
            merged = copy.deepcopy(DEFAULT_CONFIG)
            # 合并 global，缺失字段用默认值补齐
            global_cfg = data.get("global")
            if isinstance(global_cfg, dict):
                merged["global"].update(global_cfg)

            # 清洗 devices：只保留同时含 name 与 host 的条目
            devices = data.get("devices")
            clean = []
            if isinstance(devices, list):
                for d in devices:
                    if isinstance(d, dict) and d.get("name") and d.get("host"):
                        clean.append({
                            "name": str(d["name"]).strip(),
                            "host": str(d["host"]).strip(),
                        })
            merged["devices"] = clean
            self._data = merged

        # 首次运行 / 文件损坏时，落盘一份规范配置
        self.save()
        return self

    def snapshot(self):
        """@brief 返回配置的深拷贝，供多线程安全读取。

        @return dict 配置快照（含 global 与 devices）
        @author linexx
        """
        with self._lock:
            return copy.deepcopy(self._data)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save(self):
        """@brief 原子写配置：先写临时文件再 os.replace，避免半写损坏。

        @author linexx
        """
        with self._lock:
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)

    # ------------------------------------------------------------------
    # 变更（写后触发 on_change，用于热加载）
    # ------------------------------------------------------------------
    def add_device(self, name, host):
        """@brief 新增设备。

        @param name 设备名称（唯一主键）
        @param host 主机名或 IP 地址
        @raise ValueError 名称为空、host 为空或名称已存在时抛出
        @author linexx
        """
        name = (name or "").strip()
        host = (host or "").strip()
        if not name:
            raise ValueError("设备名称不能为空")
        if not host:
            raise ValueError("主机/IP 不能为空")
        with self._lock:
            if any(d["name"] == name for d in self._data["devices"]):
                raise ValueError("设备名称已存在：%s" % name)
            self._data["devices"].append({"name": name, "host": host})
            self._data["devices"].sort(key=lambda d: d["name"])
            self.save()
        self._notify_change()

    def update_device(self, name, host):
        """@brief 更新指定设备的 host。

        @param name 设备名称
        @param host 新的主机名或 IP 地址
        @raise ValueError host 为空或设备不存在时抛出
        @author linexx
        """
        name = (name or "").strip()
        host = (host or "").strip()
        if not host:
            raise ValueError("主机/IP 不能为空")
        with self._lock:
            for d in self._data["devices"]:
                if d["name"] == name:
                    d["host"] = host
                    self.save()
                    self._notify_change()
                    return
        raise ValueError("设备不存在：%s" % name)

    def rename_device(self, old_name, new_name, new_host):
        """@brief 重命名设备（name 是主键）并更新 host，原子完成。

        @param old_name 原设备名称
        @param new_name 新设备名称
        @param new_host 新主机名或 IP 地址
        @raise ValueError 名称为空、名称冲突或设备不存在时抛出
        @author linexx
        """
        new_name = (new_name or "").strip()
        new_host = (new_host or "").strip()
        if not new_name:
            raise ValueError("设备名称不能为空")
        if not new_host:
            raise ValueError("主机/IP 不能为空")
        with self._lock:
            if new_name != old_name and any(
                    d["name"] == new_name for d in self._data["devices"]):
                raise ValueError("设备名称已存在：%s" % new_name)
            for d in self._data["devices"]:
                if d["name"] == old_name:
                    d["name"] = new_name
                    d["host"] = new_host
                    self._data["devices"].sort(key=lambda x: x["name"])
                    self.save()
                    self._notify_change()
                    return
        raise ValueError("设备不存在：%s" % old_name)

    def remove_device(self, name):
        """@brief 删除设备。

        @param name 设备名称
        @raise ValueError 设备不存在时抛出
        @author linexx
        """
        with self._lock:
            before = len(self._data["devices"])
            self._data["devices"] = [
                d for d in self._data["devices"] if d["name"] != name
            ]
            if len(self._data["devices"]) == before:
                raise ValueError("设备不存在：%s" % name)
            self.save()
        self._notify_change()

    def update_global(self, **kwargs):
        """@brief 更新全局参数（仅接受已知 key，未知 key 忽略）。

        @param kwargs 全局参数键值对，如 ping_interval=5、api_port=8080
        @author linexx
        """
        with self._lock:
            g = self._data["global"]
            changed = False
            for key, value in kwargs.items():
                if key in g and g[key] != value:
                    g[key] = value
                    changed = True
            if changed:
                self.save()
        if changed:
            self._notify_change()

    def get_device(self, name):
        """@brief 查询单个设备配置。

        @param name 设备名称
        @return dict 设备配置（name/host），不存在返回 None
        @author linexx
        """
        with self._lock:
            for d in self._data["devices"]:
                if d["name"] == name:
                    return dict(d)
        return None

    # ------------------------------------------------------------------
    # 变更订阅
    # ------------------------------------------------------------------
    def set_on_change(self, callback):
        """@brief 设置配置变更回调（热加载入口）。

        @param callback 无参回调函数
        @author linexx
        """
        with self._lock:
            self._on_change = callback

    def _notify_change(self):
        """@brief 在锁外触发变更回调，避免回调内再入锁导致死锁。

        @author linexx
        """
        cb = self._on_change
        if cb is not None:
            cb()
