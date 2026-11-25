# 点巡工作台验证记录

日期：2026-11-25

## 结果

已按确认的工作台原型完成自动点击界面，并修复方案持久化与切换、点位测试、长间隔停止响应，以及脚本错误显示和运行状态恢复。

## 自动化检查

- `python -m unittest discover -s tests -v`：29 项通过，包含方案保存/切换/导入导出、点位编辑、点位测试、暂停/停止和脚本错误处理。
- `python -m compileall -q UIFunc.py UIWorkbench.py Util Event Plugin 点巡.py`：通过。
- 测试进程打印了当前机器 NumPy 2.4.6 与一个 NumPy 1.x 编译扩展的兼容提示；测试仍全部通过。该提示来自本机测试依赖，不影响打包程序启动。

## Windows 实机流程

通过 `tools/verify_workbench_ui.py` 在临时数据目录中启动真实 Qt 界面，实际输入只发往验证专用点击计数器。以下流程均通过：

- 左键双击、右键单击和中键单击的实际输入。
- F7 启动并按点击数结束；F7 暂停/继续；F8 在 60 秒等待期间停止。
- 暂停状态下把鼠标移到左上角停止。
- 屏幕拾点、F4 连续采点和 Escape 取消。
- F10 录制、F9 保存、F6 重放。
- 无效脚本显示 `scripts[1].events[1]` 动作位置，任务状态复位且运行按钮恢复。

本轮在改名后的项目目录中完成实机运行，60 秒等待时停止在单次采样精度内响应（报告为 0 ms）；暂停时角落停止在 31 ms 内响应。最新报告中的状态为 `passed`，结束时无按下未释放的键，运行状态为 `IDLE`。

## 打包冒烟

- 程序：`dist/点巡.exe`。
- 使用独立临时 `LOCALAPPDATA` 启动；确认窗口标题、工作台、快捷键与运行设置、悬浮控制均可正常打开和返回。临时目录在检查后移除。
- 打包检查覆盖启动和主要窗口切换；真实点击与脚本流程由上面的源码 Windows 实机自动化执行。
- 当前 Windows 可执行文件 SHA-256：`8DF72190B8931C558765480504004E2282D645372198B71513458B26D2BD4189`。

## 证据

- 自动化实机报告：[verification-current/desktop-report.json](verification-current/desktop-report.json)
- 最终打包版启动报告：[verification-current/packaged-report.json](verification-current/packaged-report.json)
- 工作台与脚本错误界面：[verification-current/workbench-desktop.png](verification-current/workbench-desktop.png)、[verification-current/workbench-script-error.png](verification-current/workbench-script-error.png)
- 打包版运行设置与悬浮控制：[verification-current/packaged-settings.png](verification-current/packaged-settings.png)、[verification-current/packaged-floating.png](verification-current/packaged-floating.png)

## 用户数据

项目目录中的 `config.ini` 在开始和结束时 SHA-256 均为 `A3BBAF293FDFA2101A372B2EC8D4666E47CD85EAAE34A244C5C81A23EB88C282`。所有自动化流程和打包冒烟均使用隔离的临时数据目录，没有写入此配置。
