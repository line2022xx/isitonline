# IsItOnline — 服务器设备在线监控

在 Windows 服务器上运行，通过 ping 检测多个设备是否在线，记录上下线日志，提供 GUI 界面和 HTTP REST API。纯 Python 标准库实现，零第三方依赖，可离线打包为单个 exe。

## 功能

- **ping 检测**：ping 通即认为设备在线；连续 `fail_threshold` 次失败才判定离线（防抖动）。
- **上下线日志**：设备上线/下线时记录事件，日志按天轮转保存在 `logs/events.log`。
- **多设备配置**：GUI 中增删改设备，配置保存在 `devices.json`。
- **服务端设置**：GUI「设置」中配置轮询间隔、Ping 超时、防抖阈值、API 监听地址与端口；ping 参数即时生效，API 参数改动自动重启 API 服务。
- **开机自启**：GUI「设置」中勾选后，用户登录 Windows 即自动运行（注册表 HKCU Run 键，无需管理员权限）。
- **GUI 界面**：实时显示各设备状态（在线绿/离线红）、最后检查时间、状态持续时长。
- **HTTP REST API**：对外查询在线状态。
- **长时间稳定运行**：后台线程 ping、GUI 用定时器刷新，不阻塞不冻结。

## 运行

源码运行（需 Python 3.8+）：

```bash
python main.py
```

或打包后运行 `IsItOnline.exe`（无需安装 Python）。

## 配置

配置文件 `devices.json` 首次运行自动生成，位于程序（或 exe）同目录；也可通过 GUI「设置」界面修改，无需手改文件。

```json
{
  "global": {
    "ping_interval": 5,
    "ping_timeout": 2000,
    "fail_threshold": 3,
    "api_host": "127.0.0.1",
    "api_port": 8080
  },
  "devices": [
    { "name": "核心服务器", "host": "192.168.1.10" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `ping_interval` | 轮询间隔（秒） |
| `ping_timeout` | 单次 ping 超时（毫秒） |
| `fail_threshold` | 连续失败 N 次判定离线（防抖动） |
| `api_host` | API 监听地址（`0.0.0.0` 允许外部访问，`127.0.0.1` 仅本机） |
| `api_port` | API 监听端口 |

## REST API

| 端点 | 说明 |
|---|---|
| `GET /api/status` | 全部设备状态 |
| `GET /api/status/<名称>` | 单个设备状态（中文名需 URL 编码） |
| `GET /api/health` | 健康检查 |
| `GET /api/events?n=100` | 最近 N 条上下线事件 |

示例：

```bash
curl http://127.0.0.1:8080/api/status
```

返回（`last_checked` / `since` 为 Unix 时间戳，秒）：

```json
{
  "count": 2,
  "generated_at": "2026-10-17 16:15:22",
  "devices": [
    { "name": "本机回环", "host": "127.0.0.1", "online": true,
      "last_checked": 1792224922.41, "since": 1792224915.40 }
  ]
}
```

## 离线打包为 exe

双击 `build.bat`，或手动执行：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name IsItOnline main.py
```

产物在 `dist/IsItOnline.exe`。单文件 exe 拷到任意 Windows 机器即可运行，配置与日志写入 exe 同目录。构建机需 64 位 Python 3.12（与目标系统一致）。

## 目录结构

```
isitonline/
├── main.py        # 入口，组装与启动顺序
├── config.py      # devices.json 读写、原子写、热加载
├── monitor.py     # 监控引擎（后台 ping、状态缓存、上下线裁决）
├── eventlog.py    # 事件日志 + 运行日志
├── api.py         # HTTP REST API
├── gui.py         # tkinter 界面（含设备管理与服务端设置）
├── autostart.py   # 开机自启（注册表 HKCU Run 键）
├── build.bat      # 打包脚本
└── devices.json   # 运行时配置（首次运行生成）
```

## 修改日志

- v1.0 (2026-10-17) 修改人：linexx — 初始版本：设备在线监控、上下线日志、GUI 界面、HTTP REST API、exe 打包。
- v1.1 (2026-10-17) 修改人：linexx — 新增服务端设置界面（轮询间隔/Ping超时/防抖阈值/API地址/API端口），API 监听参数不再写死并支持热重启；全模块补 Doxygen 注释规范。
- v1.2 (2026-10-17) 修改人：linexx — 新增开机自启功能（注册表 HKCU Run 键，无需管理员权限），设置界面增加开机自启开关。
