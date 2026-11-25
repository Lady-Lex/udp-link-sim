# UdpLinkSim v0.1 — 里程碑状态与验证证据

最后更新：2026-11-25

## 已验证里程碑

### 基线与仓库卫生 — 已完成
- 初始化 Git 仓库并提交脱敏基线 `legacy.py` 与 `PLAN.md`（提交 `271e062`）。
- `.gitignore` 已忽略 `.venv/`、`venv/`、`build/`、`dist/`、`__pycache__/`、临时文件与本地日志。
- 无管理员权限请求、无驱动安装、无防火墙修改、未改动任何既有部署。

### M0（环境、现代中文 QML GUI、单文件打包与强退生命周期） — 已验证
- Python 3.14.6 虚拟环境，锁定 `PySide6==6.12.0`、`pyinstaller==6.22.3`（`requirements.txt`），以及 `pytest==9.2.0`、`psutil==7.2.2`（`requirements-dev.txt`）。
- 实现现代中文浅色/深色高 DPI Qt Quick/QML 界面（`src/udplinksim/gui/qml/`）：左侧实时规则表、右侧属性面板、底部监听诊断与运行日志。
- `--engine` 在导入任何 PySide6/Qt 模块之前直接分发，由 `tests/test_lifecycle.py::test_engine_only_dispatch_does_not_import_qt` 验证通过（`QT_LOADED=False`）。
- 打包单文件 Windows x64 `dist/UdpLinkSim.exe`（57.94 MB，SHA256 `ab8140ccf3369871e91365b661eda67423e5f189567fc7dc76fc343da045b1a5`）：
  - `scripts/verify_exe.py` 实测 GUI QML 就绪 888–1216 ms（含 onefile 自解压 6.53–7.26 s），0 条 stderr 警告。
  - `--engine` 就绪 4.52–4.58 s（含 onefile 自解压），定时器 `win32_high_res_waitable`。
  - 强制终止 GUI 进程后（Win32 Job Object + 父进程句柄监控 + stdin EOF），所有引擎子进程退出且 UDP 端口在 **70.02 ms** 内释放。

### M1（核心转发语义、CSV、有界队列、定时唤醒、统计与编辑） — 已验证
- 全部 **34 项** `pytest` 自动化测试通过（5.29 s）：
  - `tests/test_config.py`：兼容 8 列基线 CSV（默认 `loss_pct=0`）、9 列含 `loss_pct`、UTF-8 BOM、原子保存；严格拒绝非法 IP/`0.0.0.0`/越界端口/相等端点/NaN/Inf/负延迟/越界丢包/空配置/歧义重复；允许同监听精确匹配 + 同 IP 端口 0 通配。
  - `tests/test_win_timer.py`：高分辨率可等待定时器 `win32_high_res_waitable`、传统 1ms 回退 `win32_legacy_waitable_1ms`、跨线程唤醒即时打断长等待。
  - `tests/test_engine.py`：4 共享绑定 Socket / 8 方向全双工、源端口保留、精确优先于端口 0 通配、两个变化源端口转发到固定目标、空 0B 与任意二进制数据报完整保留、先到 100ms 后到 5ms 即时唤醒发送、0%/50%/100% 独立伯努利丢包、非负截断高斯延迟允许乱序、包数与字节数双维有界队列 drop-new 溢出统计、未匹配对端记录（`last_unmatched_peer`）、`WSA10054` 计数且不中断转发、停止/重启精确统计 `discarded_pending` 且零旧包残留发送。
  - `tests/test_lifecycle.py`：无 Qt 分发、子进程 250ms 统计、重启释放旧端口、强杀父进程自动回收子引擎与端口。
  - `tests/test_gui.py`：新增/编辑/复制/删除/导入/保存/待应用提示/应用并重启/浅深主题切换、真实 QML 窗口零错误加载。
- 定时器与有界自旋 A/B 实测及短时基准（含单路突发与 GUI 并发）见 `reports/M0_M1_benchmark.md`、`reports/ab_benchmark.json`、`reports/short_benchmark.json`。

### M2（可用 RC 版本） — 已验证
- 基于 A/B 实测将默认有界自旋设为 `500 us`（最差单路 P99 从 `1.400 ms` 降至 `0.961 ms`，p50 降至 `0.086 ms`），全量回归测试通过并重打验证 `UdpLinkSim.exe`。
- 已打 RC 标签 `v0.1.0-rc1`（提交 `f608427`）。

### M3（30 分钟长稳压测与版本发布） — 已验证
- 针对最终打包单文件 `UdpLinkSim.exe` 完成完整 **30 分钟（1800 s）** 4 共享端口 / 8 方向 / 固定 20 ms / 800 pps 长稳压测（含每 5 分钟单路 200 包突发与并发 GUI 运行），详细数据见 `reports/M3_soak_report.md` 与 `reports/soak_30min.json`：
  - 稳态 **1,440,000 / 1,440,000**、突发 **1,000 / 1,000** 全部送达，0 坏包/错源端口/错序/重复。
  - 全部 8 方向 `send_call - deadline` P99 在 `0.806–0.901 ms` 之间（最差单路 **0.901 ms** < 1 ms 期望目标，p50 `0.081 ms`；VM 调度最大长尾 `56.795 ms`）。
  - 独立接收端 E2E 延迟 p50 `20.416 ms` / p99 `21.305 ms`；引擎单核平均 CPU `14.22%`，峰值 RSS `33.70 MB`；GUI 平均 CPU `0.79%`。
- 已生成 `SHA256SUMS.txt`，完成全部 40 个文件脱敏检查（0 敏感项），发布至公共仓库 `Lady-Lex/udp-link-sim` 与 `v0.1.0` Release（附 `UdpLinkSim.exe` 与 `SHA256SUMS.txt`）。

---

## 已知边界与后续待办（v0.1 范围之外 / 未执行项诚实声明）

1. **交互式人工桌面点击走查**：自动化测试已覆盖 QML 完整加载、零警告启动、所有 `AppController` 槽函数与真实 GUI 并发运行，但未在物理显示器上进行人工视觉逐像素截图/拖拽审查（若需进一步打磨高 DPI 125%/150%/200% 缩放细节，建议在目标桌面实机走查）。
2. **非回环多网卡真实物理网络压测**：全部测试与 30 分钟压测均在本地回环（`127.0.0.1`）独立端点完成（遵循项目范围不修改站点配置/防火墙原则），未跨真实局域网多主机实测。
3. **PyInstaller onefile 启动解压耗时**：单文件 `UdpLinkSim.exe` 启动包含约 4–5 s 的自解压开销（GUI 重启子引擎约 4.5 s）；如后续版本追求 < 500 ms 引擎重启速度，可在 v0.2 考虑提供 onedir 便携压缩包或独立轻量纯 Python 引擎二进制作为可选项。
4. **v0.2 可选增强项（不在 v0.1 范围内）**：界面内直接调节队列上限/自旋参数、GUI 实时延迟直方图、IPv6 支持、相关丢包模型（Gilbert-Elliott）。
