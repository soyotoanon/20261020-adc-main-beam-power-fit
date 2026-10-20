"""556 nm single-beam MOT power calibration desktop UI."""
import csv
import json
import math
import queue
import random
import threading
import time
import sys
import io
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"vendor"))
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from core import Parser, Point, encode_frame, fit, continuous_point
from storage import write_snapshot

ROOT = Path(__file__).resolve().parents[1]
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def replace_retry(source, target):
    # Antivirus/indexers/Excel can briefly hold a Windows destination.
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.04)


class App:
    def __init__(self, root):
        self.root = root
        root.title("556 nm MOT · 单束光功率标定")
        root.geometry("1320x850")
        root.minsize(1120, 760)
        root.configure(bg="#edf2f7")
        self.events = queue.Queue(maxsize=10000)
        self.stop_event = threading.Event()
        self.threads = []
        self.active = False
        self.points = []
        self.adc = [deque(maxlen=1000), deque(maxlen=1000)]
        self.reference = deque(maxlen=1000)
        self.last_seq = [None, None]
        self.dropped = 0
        self.raw_file = None
        self.session_dir = None
        self.current = None
        self.last_draw = 0
        self.auto = tk.BooleanVar(value=False)
        self.save_notice = ""
        self.last_pair_time = 0
        self.mode = tk.StringVar(value="演示")
        self.port = tk.StringVar()
        self.serial = tk.StringVar(value="P2007293")
        self.channel = tk.StringVar(value="候选 0")
        self.note = tk.StringVar(value="556 nm MOT 单束；记录功率计测量平面、PD增益、ADC负载档位")
        self.manual_request = False
        self.metadata = {}
        self.build_ui()
        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.tick)

    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#edf2f7")
        style.configure("TLabel", background="#edf2f7", font=("Microsoft YaHei", 10))
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=7)
        style.configure("TLabelframe", background="#edf2f7")
        style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))
        header = ttk.Frame(self.root, padding=(20, 15))
        header.pack(fill="x")
        ttk.Label(header, text="556 nm MOT  /  单束光功率标定",
                  font=("Microsoft YaHei", 20, "bold"), foreground="#162b40").pack(side="left")
        self.badge = ttk.Label(header, text="演示数据 · 未连接硬件", foreground="#b15b00")
        self.badge.pack(side="right")
        body = ttk.Frame(self.root, padding=(16, 0, 16, 10))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=295)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        conn = ttk.LabelFrame(left, text="01  设备连接", padding=12)
        conn.pack(fill="x")
        ttk.Label(conn, text="数据来源").pack(anchor="w")
        self.mode_box = ttk.Combobox(conn, textvariable=self.mode, values=["演示", "真实功率计 + FPGA"], state="readonly")
        self.mode_box.pack(fill="x", pady=(3, 8))
        ttk.Label(conn, text="FPGA · CH340 串口 / 115200").pack(anchor="w")
        self.port_box = ttk.Combobox(conn, textvariable=self.port)
        self.port_box.pack(fill="x")
        ttk.Button(conn, text="刷新串口", command=self.refresh_ports).pack(fill="x", pady=5)
        ttk.Label(conn, text="功率计序列号 · 波长固定 556 nm").pack(anchor="w")
        self.serial_entry = ttk.Entry(conn, textvariable=self.serial)
        self.serial_entry.pack(fill="x", pady=(3, 8))
        self.connect_button = ttk.Button(conn, text="开始采集", command=self.start)
        self.connect_button.pack(fill="x")
        ttk.Button(conn, text="停止并保存", command=self.stop).pack(fill="x", pady=(5, 0))
        controls = ttk.LabelFrame(left, text="02  连续采点与配对", padding=12)
        controls.pack(fill="x", pady=12)
        self.channel_box = ttk.Combobox(controls, textvariable=self.channel,
                                       values=["候选 0", "候选 1"], state="readonly")
        self.channel_box.pack(fill="x", pady=(0, 8))
        self.channel_box.bind("<<ComboboxSelected>>", self.change_channel)
        ttk.Checkbutton(controls, text="自动记录数据点", variable=self.auto).pack(anchor="w", pady=5)
        ttk.Button(controls, text="记录当前点", command=self.capture).pack(fill="x")
        ttk.Label(controls, text="连续记录，不设稳定阈值。\n按接收时间配对，非硬件同步。", foreground="#65758a").pack(anchor="w", pady=(8, 0))
        ttk.Button(left, text="撤销最后一个拟合点", command=self.undo).pack(fill="x")
        ttk.Button(left, text="导出 CSV + 拟合 JSON + 图", command=self.export).pack(fill="x", pady=6)
        ttk.Label(left, text="测量备注").pack(anchor="w", pady=(6, 3))
        ttk.Entry(left, textvariable=self.note).pack(fill="x")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        cards = ttk.Frame(right)
        cards.pack(fill="x")
        self.power_text = tk.StringVar(value="— mW")
        self.adc_text = tk.StringVar(value="— / —")
        self.point_text = tk.StringVar(value="0")
        for title, var in [("参考光功率", self.power_text), ("候选 0 / 候选 1 · code", self.adc_text),
                           ("已记录数据点", self.point_text)]:
            card = ttk.LabelFrame(cards, text=title, padding=10)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ttk.Label(card, textvariable=var, font=("Consolas", 19, "bold"), foreground="#087f8c").pack(anchor="w")
        self.figure = Figure(figsize=(9, 5.4), dpi=100, facecolor="#ffffff")
        self.ax, self.res_ax = self.figure.subplots(2, 1, gridspec_kw={"height_ratios": [3, 1]})
        self.figure.subplots_adjust(left=.1, right=.97, top=.94, bottom=.1, hspace=.45)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=12)
        self.fit_text = tk.StringVar(value="至少记录 3 个点且功率有变化后显示拟合")
        ttk.Label(right, textvariable=self.fit_text, font=("Microsoft YaHei", 11), foreground="#163f5d").pack(anchor="w")
        self.status = tk.StringVar(value="先用演示模式检查界面；真实测量前确认 INA 对应候选通道。")
        ttk.Label(right, textvariable=self.status, wraplength=850, foreground="#596b80").pack(anchor="w", pady=8)
        self.draw()

    def refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = list(list_ports.comports())
            self.port_box["values"] = [p.device for p in ports]
            if not self.port.get() and ports:
                chosen = next((p for p in ports if "CH340" in p.description.upper()), ports[0])
                self.port.set(chosen.device)
        except ImportError:
            self.status.set("演示可直接运行；真实串口需先安装 requirements.txt 中的 pyserial。")

    def start(self):
        if self.active or any(t.is_alive() for t in self.threads):
            return
        try:
            if self.mode.get() != "演示" and not self.port.get():
                raise ValueError("请选择 FPGA 串口")
            if self.points and not messagebox.askyesno("新测量", "已有点已自动保存。开始新测量将清空当前图，是否继续？"):
                return
            self.stop_event = threading.Event()
            self.events = queue.Queue(maxsize=10000)
            self.points.clear()
            for a in self.adc:
                a.clear()
            self.reference.clear()
            self.current = None
            self.last_seq = [None, None]
            self.dropped = 0
            self.start_time = self.window_start = time.monotonic()
            self.last_pair_time = self.start_time
            self.run_mode = self.mode.get()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.session_dir = ROOT/"recordings"/(stamp+("_DEMO" if self.run_mode == "演示" else "_REAL"))
            self.session_dir.mkdir(parents=True)
            self.metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(), mode=self.run_mode,
                                 wavelength_nm=556, uart_port=self.port.get(), baud=115200,
                                 recording_mode="continuous",
                                 meter_serial=self.serial.get(), channel=self.channel.get(), config={"stability_filter": False},
                                 note=self.note.get(), synchronization="nearest host timestamp, max skew 0.2 s, not hardware sync",
                                 adc_sample_rate_hz=None if self.run_mode == "演示" else 5e6,
                                 adc_window_samples=128 if self.run_mode == "演示" else 262144,
                                 code_definition="offset binary; two-complement firmware XORs bit13 before averaging")
            self.raw_file = (self.session_dir/"raw.jsonl").open("w", encoding="utf-8")
            self.save()
        except Exception as e:
            messagebox.showerror("无法开始", str(e))
            return
        self.active = True
        self.connect_button.configure(state="disabled")
        self.mode_box.configure(state="disabled")
        self.port_box.configure(state="disabled")
        self.serial_entry.configure(state="disabled")
        self.badge.configure(text="演示数据 · 非实测" if self.run_mode == "演示" else "真实采集 · 正在连接",
                             foreground="#b15b00" if self.run_mode == "演示" else "#087f8c")
        if self.run_mode == "演示":
            targets = [self.demo_worker]
        else:
            port, serial = self.port.get(), self.serial.get()
            targets = [lambda: self.adc_worker(port), lambda: self.power_worker(serial)]
        self.threads = [threading.Thread(target=f, daemon=True) for f in targets]
        for t in self.threads:
            t.start()
        self.draw()

    def emit(self, kind, value, stamp=None):
        try:
            self.events.put((time.monotonic() if stamp is None else stamp, kind, value), timeout=.5)
        except queue.Full:
            self.stop_event.set()  # fail visibly; never silently discard raw data

    def adc_worker(self, port):
        try:
            import serial
            parser = Parser()
            with serial.Serial(port, 115200, timeout=.1) as device:
                device.reset_input_buffer()
                while not self.stop_event.is_set():
                    for record in parser.feed(device.read(max(1, min(4096, device.in_waiting)))):
                        self.emit("adc", record)
                    if parser.errors:
                        self.emit("warning", f"CRC/帧错误累计 {parser.errors}")
                        parser.errors = 0
        except Exception as e:
            self.emit("error", f"FPGA：{e}")

    def power_worker(self, serial):
        meter = None
        try:
            from devices import PM100D
            meter = PM100D(serial, 556)
            self.emit("identity", meter.identity)
            while not self.stop_event.is_set():
                begin = time.monotonic()
                power = meter.read_mw()
                end = time.monotonic()
                self.emit("power", dict(mw=power, query_start=begin, query_end=end), (begin+end)/2)
                self.stop_event.wait(.15)
        except Exception as e:
            self.emit("error", f"功率计：{e}")
        finally:
            if meter:
                meter.close()

    def demo_worker(self):
        rng = random.Random(556)
        seq = 0
        parser = Parser()
        while not self.stop_event.is_set():
            elapsed = time.monotonic()-self.start_time
            power = [0.05, .25, .5, .8, 1.1, 1.4, 1.8, 2.1][int(elapsed//5) % 8]
            for ch in range(2):
                center = 8200+(-1500*power if ch == 0 else 300)
                samples = [max(1, min(16382, round(center+rng.gauss(0, 4)))) for _ in range(128)]
                for record in parser.feed(encode_frame(seq, samples, ch << 2)):
                    self.emit("adc", record)
            if seq % 3 == 0:
                now = time.monotonic()
                self.emit("power", dict(mw=power+rng.gauss(0, .00015), query_start=now, query_end=now))
            seq += 1
            self.stop_event.wait(.0524288)

    def change_channel(self, _=None):
        if self.points:
            self.channel.set(self.metadata.get("channel", "候选 0"))
            messagebox.showinfo("保持标定通道一致", "已有拟合点时不能切换通道。请停止后开始新测量，再选通道。")
            return
        self.current = None
        self.window_start = time.monotonic()
        if self.metadata:
            self.metadata["channel"] = self.channel.get()
            self.save()

    def capture(self):
        if not self.active:
            return
        self.manual_request = True

    def accept(self, point):
        point.time_s -= self.start_time
        if self.raw_file:
            self.raw_file.write(json.dumps(dict(host_monotonic_s=time.monotonic(),kind="accepted_point", value=asdict(point)),
                                           ensure_ascii=False, allow_nan=False)+"\n")
            self.raw_file.flush()
        self.points.append(point)
        self.window_start = time.monotonic()
        self.current = None
        self.save()
        self.draw()

    def undo(self):
        if self.points:
            self.points.pop()
            self.save()
            self.draw()

    def save(self):
        if not self.session_dir:
            return
        self.metadata["note"] = self.note.get()
        result = fit(self.points)
        fields = list(Point.__dataclass_fields__)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(asdict(p) for p in self.points)
        saved = write_snapshot(self.session_dir/"points.csv", stream.getvalue())
        alternate = [saved.name] if saved.name != "points.csv" else []
        for name, value in [("metadata.json", self.metadata), ("fit.json", result)]:
            target = self.session_dir/name
            saved = write_snapshot(target, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
            if saved != target:
                alternate.append(saved.name)
        self.save_notice = ("文件占用，已另存完整快照："+", ".join(alternate)) if alternate else ""

    def export(self):
        if not self.session_dir:
            return
        try:
            self.save()
            self.figure.savefig(self.session_dir/"calibration.png", dpi=170)
            messagebox.showinfo("已导出", str(self.session_dir))
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def stop(self):
        self.active = False
        self.stop_event.set()
        self.current = None
        self.manual_request = False
        save_error = None
        try:
            self.save()
        except Exception as e:
            save_error = str(e)
        finally:
            if self.raw_file:
                try:
                    self.raw_file.flush()
                finally:
                    self.raw_file.close()
                    self.raw_file = None
        self.connect_button.configure(state="normal")
        self.mode_box.configure(state="readonly")
        self.port_box.configure(state="normal")
        self.serial_entry.configure(state="normal")
        self.badge.configure(text="已停止 · 保存失败" if save_error else ("已停止 · 数据已保存" if self.session_dir else "未连接"))
        if save_error:
            self.status.set("保存失败，请关闭占用 CSV 的程序后重试导出："+save_error)

    def close(self):
        self.stop()
        self.root.destroy()

    def tick(self):
        try:
            for _ in range(500):
                try:
                    stamp, kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if not self.active:
                    continue
                if self.raw_file:
                    self.raw_file.write(json.dumps(dict(host_monotonic_s=stamp, kind=kind, value=value),
                                                   ensure_ascii=False, allow_nan=False)+"\n")
                if kind == "adc":
                    ch = value["channel"]
                    previous = self.last_seq[ch]
                    if previous is not None:
                        delta = (value["seq"]-previous) & 0xffffffff
                        if delta != 1:
                            self.dropped += 1 if delta > 0x7fffffff else max(1, delta-1)
                    self.last_seq[ch] = value["seq"]
                    self.adc[ch].append((stamp, value))
                elif kind == "power":
                    if value["query_end"]-value["query_start"] > .5:
                        self.reference.clear()
                        self.window_start = time.monotonic()
                    else:
                        self.reference.append((stamp, value["mw"]))
                elif kind == "identity":
                    self.metadata["meter_identity"] = value
                    self.save()
                    self.badge.configure(text=f"{value['model']} 已连接 · 556 nm")
                elif kind == "error":
                    self.stop()
                    self.status.set(value)
                    messagebox.showerror("采集已停止", value)
                elif kind == "warning":
                    self.metadata.setdefault("warnings", []).append(value)
            if self.active:
                now = time.monotonic()
                if self.stop_event.is_set():
                    self.stop()
                    self.status.set("采集队列满或线程停止；数据未继续配对。")
                else:
                    ch = int(self.channel.get()[-1])
                    self.current = None
                    state = "连续采点：功率波动不拦截，按时间就近配对"
                    for stamp, power in self.reference:
                        if stamp <= self.last_pair_time or now-stamp < .12:
                            continue
                        self.last_pair_time = stamp
                        if now-stamp > .8:
                            continue
                        point = continuous_point(self.adc[ch], stamp, power, self.run_mode)
                        if point is not None:
                            self.current = point
                            if self.auto.get() or self.manual_request:
                                self.accept(point)
                                self.manual_request = False
                    if not self.adc[ch]:
                        state = "未收到 FPGA 有效数据：检查串口数据与固件"
                    elif now-self.adc[ch][-1][0] > .35:
                        state = "FPGA 数据已中断或过期"
                    elif not self.reference or now-self.reference[-1][0] > .8:
                        state = "等待功率计新鲜读数"
                    self.status.set(f"{state}  |  序号异常/丢帧 {self.dropped}  |  文件：{self.session_dir.name}"
                                    + (f"  |  {self.save_notice}" if self.save_notice else ""))
                    self.power_text.set(f"{self.reference[-1][1]:.6f} mW" if self.reference and now-self.reference[-1][0] < .8 else "— 过期/未连接")
                    values = [f"{a[-1][1]['mean']:.2f}" if a and now-a[-1][0] < .35 else "—" for a in self.adc]
                    self.adc_text.set(" / ".join(values))
                    if self.manual_request:
                        self.manual_request = False
                        if self.current is None and not self.points:
                            self.status.set(state)
                    if self.raw_file:
                        self.raw_file.flush()
                    if now-self.last_draw > .5:
                        self.draw()
            self.root.after(80, self.tick)
        except Exception as e:
            self.stop()
            self.status.set(f"保存/处理失败：{e}")
            messagebox.showerror("采集停止", str(e))
            self.root.after(80, self.tick)

    def draw(self):
        self.last_draw = time.monotonic()
        self.ax.clear()
        self.res_ax.clear()
        self.ax.set_title("功率 → ADC 数字码" + ("  [DEMO]" if self.metadata.get("mode", self.mode.get()) == "演示" else ""), loc="left", fontsize=12)
        self.ax.set_xlabel("556 nm 单束 MOT 参考功率 / mW")
        self.ax.set_ylabel("ADC 均值 / code")
        self.ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        self.res_ax.set_xlabel("参考功率 / mW")
        self.res_ax.set_ylabel("残差 / code")
        for ax in [self.ax, self.res_ax]:
            ax.grid(True, color="#e3eaf0")
            for spine in ax.spines.values():
                spine.set_color("#d5dfe8")
        self.res_ax.axhline(0, color="#8a9aaa", linewidth=1)
        preview = False
        if self.active:
            ch = int(self.channel.get()[-1])
            now = time.monotonic()
            if (self.adc[ch] and self.reference
                    and now-self.adc[ch][-1][0] < .35
                    and now-self.reference[-1][0] < .8):
                self.ax.scatter([self.reference[-1][1]], [self.adc[ch][-1][1]["mean"]],
                                facecolors="none", edgecolors="#a0aab4", s=70,
                                label="实时预览（未同步，不参与拟合）")
                preview = True
        if self.points:
            x = [p.power_mw for p in self.points]
            y = [p.code for p in self.points]
            self.ax.scatter(x, y, color="#087f8c", s=22, label="已记录数据点")
            result = fit(self.points)
            if result:
                a, b = result["slope_code_per_mw"], result["intercept_code"]
                bounds = [min(x), max(x)]
                self.ax.plot(bounds, [a*v+b for v in bounds], color="#e18b36", label="线性拟合")
                self.res_ax.scatter(x, result["residual"], color="#087f8c", s=20)
                r2 = "无定义" if result["r2"] is None else f"{result['r2']:.6f}"
                self.fit_text.set(f"C = ({a:.6g}) × P[mW] + ({b:.6g})    R² = {r2}    RMSE = {result['rmse_code']:.4g} code\n"
                                  f"标定范围 {min(x):.5g}–{max(x):.5g} mW；区间外不外推。残差是拟合偏离，不是完整测量不确定度。")
            else:
                self.fit_text.set("至少 3 个点且功率有变化后拟合。")
        else:
            self.fit_text.set("至少记录 3 个点且功率有变化后显示拟合")
        if self.current:
            self.ax.scatter([self.current.power_mw], [self.current.code], s=75, marker="x",
                            color="#d08828", label="当前配对点")
        if self.points or self.current or preview:
            self.ax.legend(loc="best", fontsize=9)
        self.point_text.set(str(len(self.points)))
        self.canvas.draw_idle()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
