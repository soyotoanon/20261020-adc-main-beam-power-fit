"""Independent power calibration protocol and numerical model. Units: mW, ADC code."""
import binascii
import math
import struct
from dataclasses import dataclass, asdict
import numpy as np

PAYLOAD = struct.Struct("<2sBBIIQHHI")
FRAME_SIZE = 30


def encode_frame(seq, samples, flags=0):
    values = list(samples)
    body = PAYLOAD.pack(b"PC", 1, flags, seq, sum(values),
                        sum(v*v for v in values), min(values), max(values), len(values))
    return body + struct.pack("<H", binascii.crc_hqx(body, 0xffff))


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data):
        self.buffer.extend(data)
        records = []
        while len(self.buffer) >= FRAME_SIZE:
            if self.buffer[:2] != b"PC":
                del self.buffer[0]
                continue
            packet = self.buffer[:FRAME_SIZE]
            crc = struct.unpack("<H", packet[28:])[0]
            if binascii.crc_hqx(packet[:28], 0xffff) != crc:
                self.errors += 1
                del self.buffer[0]
                continue
            del self.buffer[:FRAME_SIZE]
            _, version, flags, seq, total, squares, low, high, count = PAYLOAD.unpack(packet[:28])
            if version != 1 or flags & ~15 or not (0 < count <= 262144) or not (0 <= low <= high <= 16383):
                self.errors += 1
                continue
            mean = total/count
            variance = squares/count - mean*mean
            if not (low <= mean <= high) or variance < -1e-6 or squares > count*16383**2:
                self.errors += 1
                continue
            records.append(dict(seq=seq, mean=mean, std=math.sqrt(max(0, variance)),
                                low=low, high=high, count=count, flags=flags,
                                total=total, squares=squares, channel=(flags >> 2) & 1,
                                twos_complement=bool(flags & 8)))
        return records


@dataclass
class Point:
    time_s: float
    power_mw: float
    code: float
    power_std_mw: float
    code_std: float
    reference_n: int
    adc_frames: int
    mode: str
    pair_skew_ms: float | None = None


def continuous_point(adc, stamp, power, mode, max_skew=.2):
    """Nearest received ADC block, host timestamps only; no stability gate."""
    if not adc or not math.isfinite(power):
        return None
    t, record = min(adc, key=lambda item: abs(item[0]-stamp))
    if abs(t-stamp) > max_skew or record["flags"] & 3:
        return None
    return Point(stamp, power, record["mean"], None, record["std"], 1, 1,
                 mode, (t-stamp)*1000)


def fit(points):
    """OLS code = slope * power_mW + intercept; no forced zero or extrapolation."""
    if len(points) < 3:
        return None
    x = np.array([p.power_mw for p in points])
    y = np.array([p.code for p in points])
    if np.ptp(x) <= max(1e-12, abs(x.mean())*1e-9):
        return None
    xc, yc = x-x.mean(), y-y.mean()
    slope = float(np.dot(xc, yc)/np.dot(xc, xc))
    intercept = float(y.mean()-slope*x.mean())
    residual = y-(slope*x+intercept)
    sse = float(np.dot(residual, residual))
    sst = float(np.dot(yc, yc))
    return dict(slope_code_per_mw=slope, intercept_code=intercept,
                r2=None if sst == 0 else 1-sse/sst,
                rmse_code=math.sqrt(sse/len(x)),
                slope_se=math.sqrt(sse/(len(x)-2)/float(np.dot(xc, xc))),
                power_min_mw=float(x.min()), power_max_mw=float(x.max()),
                residual=residual.tolist(), n=len(x))


def stable_point(adc, reference, now, start, dwell, code_span, power_fraction, power_floor, mode):
    """Host-time stable plateau matching, NOT hardware-synchronous sampling.
    Entries: (host_monotonic_time, record) or (time, power_mW).
    A fresh, continuous window is required after each accepted point.
    """
    begin = max(start, now-dwell)
    a = [(t, v) for t, v in adc if t >= begin]
    p = [(t, v) for t, v in reference if t >= begin]
    if now-start < dwell or len(a) < 5 or len(p) < 3:
        return None, "等待完整平台窗口和至少 3 次功率读数"
    if now-a[-1][0] > .35 or now-p[-1][0] > .8:
        return None, "数据过期，停止配对"
    if a[-1][0]-a[0][0] < dwell*.7 or p[-1][0]-p[0][0] < dwell*.6:
        return None, "等待覆盖整个稳定窗口"
    if any(a[i][0]-a[i-1][0] > .35 or
           ((a[i][1]["seq"]-a[i-1][1]["seq"]) & 0xffffffff) != 1 for i in range(1, len(a))):
        return None, "ADC 丢帧或重启，等待连续窗口"
    if any(p[i][0]-p[i-1][0] > .8 for i in range(1, len(p))):
        return None, "参考通道间断"
    if any(v["flags"] & 3 or v["low"] <= 0 or v["high"] >= 16383 for _, v in a):
        return None, "ADC 超量程或触及码轨，拒绝拟合"
    codes = np.array([v["mean"] for _, v in a])
    powers = np.array([v for _, v in p])
    if not np.all(np.isfinite(powers)):
        return None, "参考读数无效"
    if np.ptp(codes) > code_span:
        return None, "ADC 平台尚未稳定"
    if np.ptp(powers) > max(power_floor, abs(powers.mean())*power_fraction):
        return None, "光功率平台尚未稳定"
    return Point(now, float(powers.mean()), float(codes.mean()),
                 float(powers.std(ddof=1)), float(codes.std(ddof=1)),
                 len(p), len(a), mode), "稳定，可记录"
