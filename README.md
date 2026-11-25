# UdpLinkSim v0.1

Windows x64 IPv4 UDP 链路模拟器（延迟、高斯抖动、独立丢包、有界队列、高分辨率定时与现代中文 Qt Quick/QML 界面），以 [legacy.py](legacy.py) 为基线重构实现。

## 核心特性

- **完全兼容基线 CSV 格式**：保留 `listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms` 列，新增可选 `loss_pct` 列（默认 `0`）。兼容 UTF-8 BOM。
- **确定性路由语义**：
  - 每行表示一个转发方向；支持多个规则共享同一监听 Socket（如 4 个共享绑定 Socket / 8 条双向规则）。
  - 同一绑定 Socket 同时用于接收与发送，转发报文保留监听源端口。
  - 固定目标地址 `target_ip:target_port`，不随对端临时源端口变化而漂移。
  - 匹配顺序：**先精确匹配 `(source_ip, source_port)`，再匹配同 IP 通配端口 `0`**；严格拒绝歧义重复与非法输入。
  - 完整保留原始数据报，包括空报文（0 字节）与任意二进制负载。
- **链路损伤与队列语义**：
  - 先独立伯努利丢包（`loss_pct`），再独立采样非负截断高斯延迟 `max(0, N(base_ms, sigma_ms))`（允许乱序）。
  - 按单规则与全局双维有界队列（包数 + 字节数），溢出时丢弃新包（drop-new）。
  - 清晰区分统计项：主动丢包（`loss_drops`）、未匹配（`unmatched_packets` 与每监听端口 `last_unmatched_peer`）、队列溢出（`overflow_drops`）、发送错误（`send_errors`）、Windows `WSA10054` 与重启/停止丢弃在途包（`discarded_on_stop`）。
- **独立引擎进程与高精度定时**：
  - 启动 `--engine` 时在导入任何 PySide6/Qt 模块之前直接分发，零 Qt 开销。
  - 基于单调 QPC 绝对截止时间、最早截止时间小顶堆、收发分离与事件唤醒（新到更早报文立即唤醒定时器线程，不被先前长延迟阻塞）。
  - 优先使用 Windows 高分辨率可等待定时器（`CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`），支持自动回退到传统 1ms 可等待定时器（`timeBeginPeriod(1)`）。
  - 基于实测 A/B 数据默认启用 500 µs 有界自旋（可通过 `--spin-us 0` 关闭）。
  - 使用 Win32 Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）+ 父进程句柄监控 + 标准输入管道 EOF 三重保障：即便 GUI 被强杀，子引擎进程也会立即退出并释放全部 UDP 端口。
- **现代中文高 DPI 界面（PySide6 Qt Quick / QML）**：
  - 支持浅色 / 深色模式一键切换。
  - 左侧实时规则表（250ms 刷新）、右侧属性编辑与即时校验、底部监听诊断与运行日志。
  - 显示当前配置文件路径、未保存与待应用状态；支持新增、编辑、复制、删除、导入 CSV、原子保存、应用并重启引擎（无旧引擎残留发送）。

## 快速开始

### 直接使用打包可执行文件（Windows x64）

从 GitHub Releases 下载 `UdpLinkSim.exe` 与 `SHA256SUMS.txt`：

```powershell
# 校验 SHA256
Get-FileHash .\UdpLinkSim.exe -Algorithm SHA256

# 启动 GUI（可选指定初始配置）
.\UdpLinkSim.exe --config .\examples\loopback_4ports_8rules.csv

# 独立无界面引擎模式（不加载 Qt）
.\UdpLinkSim.exe --engine --config .\examples\loopback_4ports_8rules.csv
```

### 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 启动 GUI
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m udplinksim --config .\examples\loopback_4ports_8rules.csv

# 运行全部自动化测试
.\.venv\Scripts\python.exe -m pytest -v

# 构建单文件 UdpLinkSim.exe 与 SHA256SUMS.txt
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

## 示例配置

- [examples/loopback_4ports_8rules.csv](examples/loopback_4ports_8rules.csv)：4 共享监听端口 / 8 方向回环示例（9 列含 `loss_pct`）。
- [examples/loopback_legacy_8col.csv](examples/loopback_legacy_8col.csv)：兼容基线 8 列格式示例（含通配 `source_port=0`）。

## 实测报告与里程碑状态

- [STATUS.md](STATUS.md)：已验证里程碑、证据索引与未完成项诚实记录。
- [reports/M0_M1_benchmark.md](reports/M0_M1_benchmark.md)：打包启动、A/B 定时器与自旋对比、短时基准与突发/GUI 并发实测。
- [reports/M3_soak_report.md](reports/M3_soak_report.md)：30 分钟 4 端口 / 8 方向（800 pps）长稳压测实测报告。
