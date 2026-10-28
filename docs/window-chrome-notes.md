# WindowChrome 闪烁问题与最小化还原修复记录

更新日期：2026-10-26

## 最终结论

Windows 下“最小化 → 正常窗口”和“最小化 → 最大化窗口”的还原黑闪、背景板先显示问题曾在真实 Gallery 目测中通过。后续复测确认效果受电源和性能状态影响：插电时正常，使用电池时仍可能出现短暂背景板，因此不能把当时结果视为所有环境下均已根治。

最终方案保留原生任务栏、DWM 还原动画和现有 Tk 控件，不需要 DirectComposition，不切换原生标题栏，也不通过隐藏真实窗口或透明度来掩盖绘制过程。`gallery.py` 没有为此修改。

核心思路来自用户：**不要等窗口展开后再逐个绘制控件，而是在最小化状态下先让 Tk 完成目标尺寸的布局和绘制，再开始 DWM 还原动画。**

## 最终实现

相关文件：

- `tkwin11/window_chrome.py`：还原状态记录、Tk 主线程预绘制、原生还原和擦除保护。
- `tkwin11/restore_animation.py`：短期静态画面、动画期间遮挡及最终资源释放。
- `tests/check_window_chrome.py`：普通还原、快速状态回归和最大化状态保持检查。

### 1. 最小化前保存完整画面

使用屏幕 `BitBlt` 捕获窗口内容。`PrintWindow` 在此项目的回归中会失败或漏掉 ttk 内容，因此没有采用。

已有完整截图时不使用后续过渡帧覆盖它，避免把标题或控件已经擦除的画面当成最终静态图。

### 2. 在 Tk 主线程预绘制

Win32 窗口过程只拦截 iconic 状态下的 `SC_RESTORE` 并设置请求标志，不直接调用 Tk。实际 `prepare_restore()` 由 `poll_native()` 在 Tk 主线程执行。

此前在 Win32 窗口过程中直接调用 Tk 曾触发 GIL fatal error，这一边界必须保留。

预绘制阶段：

- 普通还原使用最小化前保存的原始矩形。
- 最大化还原使用最小化前记录的工作区，不复用带不可见边框的最大化屏幕矩形。
- 调用 `root.update_idletasks()`，让 Tk 先完成目标尺寸的布局。
- 调用 `RedrawWindow` 请求真实控件完成绘制。
- 最后才调用 `ShowWindow(SW_RESTORE)` 或 `ShowWindow(SW_MAXIMIZE)`，启动原生 DWM 动画。

因此，DWM 展开的是已经接近最终内容的窗口，而不是展开一个只有背景色、控件尚未布局完成的空窗口。

### 3. 静态画面嵌入真实窗口内部

静态图使用真实窗口内部的 `Static` 子 HWND 承载，而不是独立置顶覆盖窗口。它会跟随父窗口参与 DWM 动画，并在真实控件已经预绘制后提供短暂的完整画面。

还原交接当前使用 `HANDOFF_DELAY_MS = 350`。交接时先执行一次 `DwmFlush()`，再销毁静态子窗口并释放 DC、位图等资源。

每个隐藏入口会销毁旧静态层，避免桌面残留；`detach()` 会取消任务并完整释放资源。`dismiss()` 只销毁静态层并取消旧交接计时器，保留仍有效的截图供下一次状态切换使用。

## 最大化黑边的最后根因

预绘制完成后，最小化到最大化仍会出现左侧和顶部黑边，约一百多毫秒后跳到正确画面。最后确认这不是窗口目标位置错误，而是**静态截图把最大化窗口的不可见边框也截进去了**。

同一时刻实测：

- `GetWindowRect`：`(-9, -9, 1929, 1149)`，即 `1938 × 1158`。
- DWM extended frame bounds：`(0, 0, 1920, 1140)`，即实际可见工作区。
- 旧截图左侧前 9 列和顶部前 9 行全部为纯黑。

静态层从父窗口客户区 `(0, 0)` 开始绘制这张截图，于是屏幕外的 9 像素黑边被原样显示在窗口内部；静态层销毁后黑边才消失，看起来像窗口位置延迟纠正。

修复方式：当 `IsZoomed(hwnd)` 为真时，截图边界改用 `DwmGetWindowAttribute(..., DWMWA_EXTENDED_FRAME_BOUNDS, ...)`，不再直接使用包含不可见调整边框的 `GetWindowRect`。

修正后实测截图从 `(0, 0)` 开始，尺寸为 `1920 × 1140`，左侧和顶部原黑边位置均为真实 UI 像素。普通窗口仍沿用原截图路径。

## 已通过的验证

真实 Gallery 由用户最终确认：

- 最小化到正常态：通过。
- 最小化到最大化：通过。
- 两条路径均无此前的背景板、黑边和控件逐步加载现象。
- 原生 DWM 还原动画保留。

自动检查：

```bash
python -m compileall -q tkwin11 gallery.py tests/check_window_chrome.py
python tests/check_window_chrome.py
git diff --check -- tkwin11/window_chrome.py tkwin11/fluent.py tkwin11/restore_animation.py tkwin11/navigation.py tests/check_window_chrome.py
```

WindowChrome 与 FluentWindowChrome 的 normal、destroy、single、override、before_attach 共 10 组测试全部通过。另用原生矩形和位图像素检查确认最大化截图不再包含屏幕外黑边。

自动连续帧采样只能辅助分析，可能漏掉肉眼可见的单帧；本次结论以真实 Gallery 的最终目测通过为准。

## 电源状态与性能影响

后续使用同一恢复点复测发现：插电时未观察到闪烁，使用电池时仍会短暂出现背景板，随后控件快速刷新出来。这表明还原效果具有明显的时间和性能依赖性，高性能电源模式可能只是缩短了可见间隔，不能据此认定所有环境下的时序问题都已消失。

后续目测必须在插电和电池两种状态下分别进行，并记录 Windows 电源模式；自动测试通过不能覆盖这一差异。纯预绘制实验中出现的背景板也说明“已发出布局或重绘请求”不等于低性能环境下“最终像素已在 DWM 动画前提交”。

## 正常到最大化的诊断与当前缓解

正常到最大化与最小化还原不是同一条路径，不能复用还原静态层来宣称已经解决。

一次性诊断探针（未进入生产代码）记录了真实 Gallery 首页的 `WM_ERASEBKGND`、`WM_PAINT`、wrapper surface 和屏幕采样：

- 1418 次背景擦除涉及的所有 HWND，其类背景刷 `hbrBackground` 都为 0，黑块不是由注册的默认黑色刷子填出。
- toolbar 已通过 `_snap_hooks` 获得部分擦除保护，不能归因于“标题栏完全未 hook”。
- 修复前 36ms 的 wrapper 采样已经有黑色区域，但内容区首绘在约 129ms、toolbar 在约 161ms、搜索框在约 219ms，证明黑帧早于对应控件绘制。
- 黑色命中区域同时包含 guard 和默认路径 HWND，因此扩大整窗 erase guard 不是正确修复。

当前 `toggle_maximize()` 在 `state()` 后执行一次 `update_idletasks()`，再执行 `RedrawWindow(RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW)`，不使用 `WM_SETREDRAW(FALSE)`：

- 实测 `RedrawWindow` 约 18.65ms；内容区首绘提前到约 37ms，toolbar 首绘提前到约 50ms，记录到的绘制在约 51ms 完成。
- 关键 Label、Entry 和 toolbar Frame 的另一轮记录均约为 32–33ms。
- 用户目测黑闪范围和时间均减少，但仍可观察，因此这是有效缓解，不是彻底修复。
- 轻量像素采样显示，大多数已确认黑点在约 41ms 恢复；toolbar 顶部 `y=2` 细条最后观测到黑色约 57ms，约 61ms 恢复。
- 第二轮 `update_idletasks()` 的黑色采样完全不变，已撤回。
- DWM `MARGINS` 的 `top=0` 使黑带延长到约 82ms、约 101ms 才恢复；`top=2` 持续到约 62ms、约 81ms 才恢复，均不如 `top=1`，已恢复为 1px。

连续帧和绘制数据保存在 `perf/results/maximize-diagnostic/`、`maximize-sync/`、`maximize-timeline/`。采样本身有开销，不能把采样时刻当作无扰动的 DWM 每帧时序。

## 保留的拖动兼容性处理

以下已认可行为不因还原修复而改变：

- 手动拖动期间，`WM_NCCALCSIZE` 使用 `rect.bottom -= 1`，规避 DWM 原生子窗口缩放瑕疵。
- DWM 顶部边距保留 1px。
- 正常到最大化时，背景擦除保护仅用于左侧栏，不接管整个右侧页面。
- 拖动期间推迟 `refresh_cache()`，退出拖动后统一刷新。
- Fluent 标题激活颜色动画在 `_native_moving` 期间暂停，结束后同步。

## 不要重复的失败方案

以下方案已经实测失败或引入回归，不能因编译、自动测试通过就重新保留：

- `WVR_REDRAW`、`WVR_VALIDRECTS`、`SWP_NOCOPYBITS`。
- `WS_CLIPCHILDREN`，包括后补样式并调用 `SWP_FRAMECHANGED`。
- DWM 垂直刷新时序同步。
- `ShowWindow` 与过渡计数挂起。
- 清除 `WS_CAPTION` 并移除 DWM 帧扩展。
- 临时切换原生标题栏，动画结束后再切回。
- 禁用 DWM 动画、冻结文字或整个子窗口树。
- 完整窗口擦除保护、交接前后强制整窗重绘。
- 截图前额外 `DwmFlush`、延长截图保留时间来掩盖交接问题。
- 独立置顶 BitBlt 覆盖窗口；最终有效的是父窗口内部静态子 HWND。
- DirectComposition 原型：具体实现未通过 Gallery 黑闪目测，最终方案也不再需要它。
- 在还原期间忽略左侧子菜单高度回写：未通过并已撤回。

## 维护边界

- 不把本次结论扩大为“所有快速连续状态切换都已验证”；快速连续切换此前已明确暂缓。
- 不修改已经认可的普通还原路径来解决最大化特有问题。
- 最大化截图必须区分原生窗口矩形与 DWM 实际可见矩形；多显示器和不同 DPI 下也不能假定不可见边框固定为 9px。
- 若后续修改交接时序，必须重新检查静态层残留、首帧空窗、真实控件提前露出和资源释放。
- 若改动窗口过程与 Tk 的交互，必须维持“窗口过程只传递数据，Tk 工作回到主线程”的规则。
