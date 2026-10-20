"""Preserve a complete snapshot even when Windows locks the usual destination."""
import time
from pathlib import Path


def write_snapshot(target, text):
    target = Path(target)
    temp = target.with_name(target.name + f".{time.time_ns()}.tmp")
    temp.write_text(text, encoding="utf-8-sig" if target.suffix == ".csv" else "utf-8")
    try:
        temp.replace(target)
        return target
    except PermissionError:
        # Never overwrite/truncate the locked file. Save a complete, uniquely named copy.
        fallback = target.with_name(f"{target.stem}_snapshot_{time.time_ns()}{target.suffix}")
        with fallback.open("xb") as stream:
            stream.write(temp.read_bytes())
        return fallback
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
