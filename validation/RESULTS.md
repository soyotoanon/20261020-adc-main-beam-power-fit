# 验证记录：2026-10-20

## 已通过

- Python：`python -m pytest outputs/power_calibration/tests -q`，结果 **6 passed in 0.22s**，无跳过。覆盖坏 CRC/截断帧重新同步、最大统计和、负斜率和退化拟合、过期/超量程/丢帧/变化平台拒收，以及两种码型的 FPGA UART 仿真结果。
- Vivado xsim：偏移二进制、二补码各输出 6 个 UART 帧；两路各序号 0、1、2，1024 点均值分别为 9000/7000，标准差 0；候选 1 的 OTR 被正确标记。测试从串口引脚解码并由 Python 复核 CRC。
- Vivado 2023.2：实际综合顶层 `calibration_top`、布局布线、bitstream 生成通过。最终 **WNS +7.713 ns，TNS 0；WHS +0.048 ns，THS 0**。报告没有未约束内部端点。
- DRC：0 个 Error，4 个 Warning，为平方运算 DSP 的输入/输出流水线建议（DPIP/DPOP）。50 MHz 时序已满足，因此没有为消除建议而增加流水级。环境启动时另有 Tcl Store 权限提示，不影响本地工程构建。
- Tk 主窗口运行真实事件循环、真实演示采集线程 19 秒，自动生成 7 个平台点，保存 CSV/JSON 并更新 Matplotlib 图。演示斜率设置为 −1500 code/mW，得到约 −1499.94 code/mW。此处数据仅用于软件验收。
- 实际导出的 `demo_plot.png` 已查看，中文标签、散点、拟合线和残差显示正常。
- 本机能枚举 `COM9 / USB-SERIAL CH340`。本次没有打开该串口，没有烧录或替换正在运行的实验固件。

## 实物与显示限制

- TLPMX DLL 可加载，但设备枚举返回 **−1073807343**，官方错误文本为 “Insufficient location information or the device or resource is not present in the system.” 因此没有完成 PM100D 实物读取、556 nm 设置回读或双设备端到端采集。COM 口存在也不等于新协议已运行。
- 新 bitstream 未上板。两相位到 INA/INB 的实际映射、PD 输入范围、模拟前端直流响应、探头口径与量程、分光稳定性，需要按 README 的步骤确认。
- 时序通过基于外部器件与线缆总延迟 ≤16 ns 的建模，不代替示波器检查实际时序与信号完整性。最终 hold 裕量见报告。
- 原生 Tk 界面的完整截图在当前执行会话不可用：屏幕抓取失败，PrintWindow 只返回黑图，因此未将其作为截图交付。真实 Tk 事件循环及采集/绘图/保存已经运行验证；完整窗口的人工视觉验收仍需在用户桌面打开。
- 一次跨执行权限的 GUI 试跑遇到 Windows 文件替换拒绝访问；程序现对短暂占用重试，并在持续保存失败时停止采集、保留原始日志和显式报错。正常权限下后续完整演示通过。

## 固件文件

`fpga/build/mot556_calibration.bit`

- 大小：2,192,123 字节
- SHA-256：`2240C2C8C2B2D9776F9A52DC3FC0EAC707158FE9F29BDF38CBF38D926A72C156`
- 构建完成时间：2026-10-20 13:52:49（Asia/Hong_Kong）
- 晚于最终采集 RTL 的修改时间；默认 `TWOS_COMPLEMENT=1`。
- 目标：ATK-DF7A35 V2.1 / XC7A35T-FGG484-2。

本工程是可交付的独立代码与离线验证固件，**不是已测出的 556 nm MOT 光标定系数**。
