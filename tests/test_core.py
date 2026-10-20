import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"host"))
import numpy as np
import pytest
from core import Parser, Point, encode_frame, fit, stable_point


def test_continuous_accepts_drift_and_checks_pair_age():
    from core import continuous_point
    adc = [(1.0, dict(mean=8000, std=3, flags=8)),
           (1.1, dict(mean=8100, std=4, flags=8))]
    p = continuous_point(adc, 1.08, .04, "real")
    assert p.code == 8100
    assert abs(p.pair_skew_ms-20) < 1e-9
    assert continuous_point(adc, 2.0, .09, "real") is None
    adc[-1][1]["flags"] = 9
    assert continuous_point(adc, 1.08, .04, "real") is None


def test_fragmented_corrupt_and_resync():
    good = encode_frame(7, [8190, 8192, 8194])
    bad = bytearray(good)
    bad[12] ^= 1
    parser = Parser()
    assert parser.feed(b"noise"+bad+good[:5]) == []
    records = parser.feed(good[5:])
    assert parser.errors >= 1
    assert len(records) == 1
    assert records[0]["mean"] == 8192
    assert abs(records[0]["std"]-np.std([8190,8192,8194])) < 1e-6


def test_maximum_accumulators():
    record = Parser().feed(encode_frame(0xffffffff, [16383]*262144, 15))[0]
    assert record["mean"] == 16383 and record["std"] == 0
    assert record["channel"] == 1 and record["twos_complement"]


def test_fit_negative_slope_and_degeneracy():
    pts = [Point(i, p, 8200-1500*p, 0, 0, 3, 10, "test") for i,p in enumerate([0,.2,.5,1])]
    result = fit(pts)
    assert abs(result["slope_code_per_mw"]+1500) < 1e-9
    assert abs(result["intercept_code"]-8200) < 1e-9
    assert result["r2"] == 1
    assert fit([pts[0]]*4) is None
    assert fit(pts[:2]) is None


def windows():
    a = [(t, dict(seq=i,mean=8000,low=7990,high=8010,flags=4)) for i,t in enumerate(np.arange(8,10.01,.05))]
    p = [(t, .5) for t in np.arange(8,10.01,.2)]
    return a,p


def check(a,p, now=10):
    return stable_point(a,p,now,8,2,20,.02,.001,"test")[0]


def test_stable_reject_stale_saturated_gap_and_transient():
    a,p = windows()
    assert check(a,p) is not None
    assert check(a,p,11) is None
    a[10][1]["flags"] = 5
    assert check(a,p) is None
    a,p = windows()
    a[10][1]["seq"] += 100
    assert check(a,p) is None
    a,p = windows()
    a[20][1]["mean"] = 8100
    assert check(a,p) is None
    a,p = windows()
    p[4]=(p[4][0],.8)
    assert check(a,p) is None


@pytest.mark.parametrize("signed", [False, True])
def test_rtl_uart_dump(signed):
    path = Path(__file__).resolve().parents[1]/"validation"/("uart_signed_hex.txt" if signed else "uart_hex.txt")
    if not path.exists():
        import pytest
        pytest.skip("Run Vivado xsim first")
    raw = bytes(int(s,16) for s in path.read_text().split())
    parser = Parser()
    records = parser.feed(raw)
    assert parser.errors == 0 and len(records) == 6
    for ch, expected in [(0,9000),(1,7000)]:
        r = [r for r in records if r["channel"] == ch]
        assert [v["seq"] for v in r] == [0,1,2]
        assert all(v["mean"] == expected and v["std"] == 0 and v["count"] == 1024 for v in r)
        assert all(bool(v["flags"] & 1) == bool(ch) for v in r)
        assert all(v["twos_complement"] == signed for v in r)
