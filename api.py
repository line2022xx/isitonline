"""HTTP REST API。

@brief 对外查询设备在线状态。
@details 基于 http.server.ThreadingHTTPServer，每个连接独立线程，独立 daemon 线程服务。
    监听地址与端口均从配置读取，不写死。
@author linexx
"""

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from config import DEFAULT_CONFIG

_APP_LOG = logging.getLogger("app")


class _ApiHTTPServer(ThreadingHTTPServer):
    """HTTP 服务器。

    @brief 携带 monitor / event_log 引用，供 handler 通过 self.server 访问。
    @author linexx
    """

    daemon_threads = True

    def __init__(self, addr, monitor, event_log):
        """@brief 构造服务器并绑定 handler。

        @param addr (host, port) 监听地址
        @param monitor Monitor 监控引擎
        @param event_log EventLog 事件日志
        @author linexx
        """
        super().__init__(addr, _Handler)
        self.monitor = monitor
        self.event_log = event_log


class _Handler(BaseHTTPRequestHandler):
    """请求处理器。

    @brief 仅支持 GET，路由到各查询端点。
    @author linexx
    """

    # 减少标准库默认的 stderr 噪音，改走 app 日志
    def log_message(self, fmt, *args):
        _APP_LOG.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        """@brief 处理 GET 请求，异常兜底返回 500。

        @author linexx
        """
        try:
            self._route()
        except Exception as e:  # 兜底，避免单次异常中断整个连接线程
            _APP_LOG.exception("API 处理异常: %s", e)
            try:
                self._send_json({"error": "internal error"}, 500)
            except Exception:
                pass

    def do_POST(self):
        self._send_json({"error": "method not allowed"}, 405)

    def do_PUT(self):
        self._send_json({"error": "method not allowed"}, 405)

    def do_DELETE(self):
        self._send_json({"error": "method not allowed"}, 405)

    # ------------------------------------------------------------------
    def _route(self):
        """@brief 按路径分发到各端点。

        @author linexx
        """
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        monitor = self.server.monitor
        event_log = self.server.event_log

        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            return

        if path == "/api/status":
            devices = monitor.get_status()
            self._send_json({
                "count": len(devices),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "devices": devices,
            })
            return

        if path.startswith("/api/status/"):
            name = unquote(path[len("/api/status/"):])
            dev = monitor.get_one(name)
            if dev is None:
                self._send_json({"error": "not found", "name": name}, 404)
            else:
                self._send_json(dev)
            return

        if path == "/api/events":
            try:
                n = max(1, min(10000, int(query.get("n", ["100"])[0])))
            except (ValueError, IndexError):
                n = 100
            events = event_log.get_recent(n)
            self._send_json({"count": len(events), "events": events})
            return

        self._send_json({"error": "not found"}, 404)

    def _send_json(self, obj, status=200):
        """@brief 发送 JSON 响应（UTF-8，中文不转义）。

        @param obj 待序列化对象
        @param status HTTP 状态码
        @author linexx
        """
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ApiServer:
    """API 服务门面。

    @brief 管理 HTTP 服务器的启停与热重启，监听配置从 config 读取。
    @author linexx
    """

    def __init__(self, monitor, config, event_log):
        """@brief 构造 API 服务。

        @param monitor Monitor 监控引擎
        @param config Config 配置对象
        @param event_log EventLog 事件日志
        @author linexx
        """
        self._monitor = monitor
        self._config = config
        self._event_log = event_log
        self._server = None
        self._thread = None
        self.last_error = None
        self.running = False

    def start(self):
        """@brief 启动 API 服务（非阻塞，独立 daemon 线程）。监听地址/端口取自配置。

        @return bool 启动成功为 True；端口占用等失败为 False（不影响主功能）
        @author linexx
        """
        g = self._config.snapshot()["global"]
        # 默认值统一来自 config.DEFAULT_CONFIG，避免散落硬编码
        host = g.get("api_host", DEFAULT_CONFIG["global"]["api_host"])
        port = int(g.get("api_port", DEFAULT_CONFIG["global"]["api_port"]))
        try:
            self._server = _ApiHTTPServer((host, port), self._monitor, self._event_log)
        except OSError as e:
            self.last_error = str(e)
            _APP_LOG.error("API 启动失败（端口占用？）%s:%s -> %s", host, port, e)
            self.running = False
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="api")
        self._thread.start()
        self.running = True
        _APP_LOG.info("API 已启动: http://%s:%s/api/status", host, port)
        return True

    def restart(self):
        """@brief 重启 API 服务，应用最新配置（用于地址/端口等参数热更新）。

        @return bool 重启成功为 True
        @author linexx
        """
        self.stop()
        return self.start()

    def stop(self):
        """@brief 停止 API 服务。

        @author linexx
        """
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self.running = False
