# M0/M1/G0 真实 Tk 场景

`scenarios.py` 是 S1–S7 的标准库场景入口，目标环境为 Windows。场景创建真实 `Tk`/`FluentSwitch`，使用 `after` 和 `mainloop` 驱动；脚本及 `scenario_support.py` 不调用 `update()` 或 `update_idletasks()`。

普通 M0 计数和耗时用于可重复性检查；`TweenProbe` 只包装当前场景内的对象，不修改生产代码。设置 `TKWIN11_PROFILE=1` 后，每轮还会在 root 销毁前保存生产 `profiling.snapshot()`，用于 M1 的 pixels/PNG/PhotoImage、update/sched/gap 和可见性分账。快照本身不直接证明性能收益。

`gallery_scenarios.py` 是 G0 全库审计入口。G1–G6 使用真实 gallery 页面、导航、折叠、非菜单弹窗、滚动、滑块和混合控件，ON/OFF 均记录应用层首次视觉提交与稳定时间；ON 另记录 operation span、DPI、布局、绘制和 Tween 分账。该指标不代表 OS 屏幕 present，也不用于未测量场景的优化声明。

```bash
# G0 全场景 smoke 与统计
python tests/gallery_run.py --scenario all --smoke --raw-dir perf/results/gallery-audit/smoke-raw
python tests/gallery_analysis.py --raw-dir perf/results/gallery-audit/smoke-raw --output perf/results/gallery-audit/smoke/statistics.json --bootstrap 200

# G0 正式 30 对采集与统计
python tests/gallery_run.py --scenario all --samples 30 --warmup 5 --seed 20250308
python tests/gallery_analysis.py --bootstrap 10000
```

## 自动运行

在仓库根目录运行：

```bash
# M0 全场景 smoke；S1 每轮自动使用一个新的 Python 进程
python tests/scenarios.py --scenario all --repeat 1

# 单场景与多轮原始样本
python tests/scenarios.py --scenario S2 --repeat 5
python tests/scenarios.py --scenario S1 --repeat 30

# 开启生产 profile 的 M0 smoke（仍使用 M0 探针）
TKWIN11_PROFILE=1 python tests/scenarios.py --scenario all --repeat 1

# M1 单轮 smoke：关闭 S3/S4/S6 的 M0 探针，改用生产 profile 验证
TKWIN11_PROFILE=1 TKWIN11_M1_MEASURE=1 \
  python tests/scenarios.py --milestone M1 --scenario all --repeat 1

# M1 正式交错采集与统计（热路径预热，冷/热均使用独立进程）
python tests/profile_run.py --scenario all --samples 30 --warmup 5 --seed 20250308
python tests/profile_analysis.py --bootstrap 10000

# 非正式采集/统计 smoke，输出明确标记 NONFORMAL
python tests/profile_run.py --scenario all --smoke
python tests/profile_analysis.py --bootstrap 200

# 显式输出路径；- 表示写到 stdout
python tests/scenarios.py --scenario all --repeat 3 --output perf/results/m0/baseline.json
python tests/scenarios.py --milestone M1 --scenario S6 --output -
```

`--scenario` 接受 `S1`…`S7` 或 `all`，`--repeat` 必须为至少 1 的整数，`--milestone` 接受 `M0`（默认）或 `M1`。默认分别输出到 `perf/results/m0/` 或 `perf/results/m1/` 下的 `scenarios_<场景>_<本地时间>.json`。全场景运行会在每个 repeat 中依次执行 S1–S7；S1 不在父进程复用 root 或缓存，子进程继承 profile 环境变量。

环境变量必须在 Python 进程启动前设置：

- `TKWIN11_PROFILE=1` 开启生产埋点，`run.profile_enabled` 记录实际状态；`--milestone M1` 本身不会开启埋点。
- `TKWIN11_M1_MEASURE=1` 进入正式测量路径：S3/S4/S6 不创建 `TweenProbe`，避免其 monkeypatch 和 4ms poll 污染 update/sched 数据。正式 on/off 两轮都设置此变量；off 只验证真实终态，on 还用生产 profile 验证计数与分账。普通 M0 smoke 不设置此变量，保留原探针和断言。

退出码：全部通过为 `0`；任一轮失败为 `1`，JSON 的该轮含场景名、轮次和 traceback；命令行参数错误为 `2`；结果写入或序列化失败为 `3`。一轮失败不会抹掉其他轮的原始结果。普通场景的 mainloop watchdog 为 15 秒，S5 为 30 秒，S1 子进程上限为 90 秒；超时按具体场景/轮次失败记录，不留下无限运行的 GUI。

场景内容：

- **S1**：新进程创建 root、应用主题、首次创建开关和首次 hover；记录冷进程、阶段耗时及帧缓存计数。
- **S2**：真实开关的 hover、press、release、on/off；经过 83ms feedback 与 167ms position 动画后检查终态，并记录 `switch_draw_count`（不是 Tcl copy 计数）。
- **S3**：同一 root 的 6 个真实开关并行 press/release，采样活跃 `Tween` 峰值并检查全部终态。
- **S4**：覆盖 unmapped、`place` 到视口外、`ScrollArea` 滚出视口后请求装饰性 hover，分别记录可见性分类和 update 数。
- **S5**：自动检查 factory 的 1/1.5/2 ratio、注册与 copy 传播，覆盖静态、hover、press、focus、disabled 和动画代表帧；focus/disabled 还比较实际 slot 像素。
- **S6（单场景）**：在 Tk 主线程对 5/25/60ms `time.sleep` 分账，不拆成新的 CLI 场景名：
  - **S6a / `channel='update'`**：在指定装饰性 Tween update 回调内注入阻塞，检查生产 `tween_update_ms`（或 M0 探针）确实包含该耗时。
  - **S6b / `channel='after'`**：保留独立 `root.after()` 阻塞，记录回调延迟和 update/gap；检查阻塞期间 update 计数与累计耗时不变，不把独立 after 阻塞冒充 update 耗时。
- **S7**：覆盖 update 内 cancel/restart、done 内 restart、owner destroy、root destroy 和两个独立 root。

S2 的 hover 使用 Tk `<Motion>` warp 加控件事件，避免机器真实指针位置覆盖合成 hover；自动运行会移动鼠标，运行期间不要操作鼠标或前台窗口。

## 原始 JSON

每份文件包含：

- `run.commit`：完整 HEAD SHA；
- `run.environment`：Windows 版本/build、架构、Python 版本/位数、Tk 版本、系统 DPI/缩放、显示器数量、电源来源/电量、活动电源方案、电源模式和系统动画状态；无法由标准库接口可靠取得的值明确记为 `unknown`；
- `run.milestone`、`run.scenario`、`run.repeat`、`run.timestamp_ns`；
- `run.profile_enabled`：由生产 `profiling.enabled()` 决定；`run.measurement_scope` 随 M0/M1 模式变化；
- `rounds[]`：每轮 `scenario`、`round`、`pass`、`duration_ms`、`error`、`counters`、`timings`、`profile`、`details`；所有原始逐轮样本均保留，不只保存汇总。profile 关闭时 `profile` 为 `null`，开启时含 `samples`、`counters`、`visibility`、`frames`、`summary`，不会在 `details` 中重复；
- `summary`：通过/失败轮数。

`*_ms` 为毫秒，`*_count` 为可观察计数。S1 阶段计时、S5 factory 计时和 S6 注入元数据不能替代顶层生产 profile 的 M1 分账；不得把单次 smoke 或人造阻塞直接写成性能改善或 M1 预算结论。

## S5 人工跨屏视觉检查

自动 factory 检查不能替代真实多显示器 DPI 变化。准备缩放分别为 100%、150%、200% 的显示器，并记录各屏实际缩放、Windows build 和 commit。

1. 运行 `python gallery.py`，进入“开关”页面，确保示例包含正常与禁用开关。
2. 分别在 100%、150%、200% 屏幕检查关/开静态面：轨道和旋钮几何清晰、尺寸比例一致、背景无异常透明或残留。
3. 在每屏执行 hover、press/release 和连续 on/off；观察 83ms feedback 与 167ms 位移动画的代表帧，不应闪白、跳回旧帧或留下错误终态。
4. 用 Tab 进入开关，检查键盘 focus 环；通过示例的禁用选项切换 disabled，检查 hover/press 不残留且禁用颜色正确。
5. 将窗口在各屏之间双向缓慢拖动，在跨 DPI 边界前后重复上述静态、focus、disabled 和动画检查。特别检查 factory 重建后的清晰度、尺寸及 slot 图像，不能只检查首次绘制。
6. 把每屏实际 DPI、操作顺序、通过/失败和异常截图与对应原始 JSON 一起归档。自动 JSON 中 `manual_cross_screen_required: true` 只表示仍需执行本步骤，不代表人工检查已通过。
