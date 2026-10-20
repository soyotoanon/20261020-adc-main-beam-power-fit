"""Runs a real Tk window and real demo acquisition thread for 19 s; no hardware."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"host"))
import tkinter as tk
from PIL import ImageGrab
from app import App, ROOT
from core import fit

root = tk.Tk()
app = App(root)
app.auto.set(True)
app.start()
errors = []


def finish():
    try:
        assert len(app.points) >= 5, len(app.points)
        result = fit(app.points)
        assert result and abs(result["slope_code_per_mw"]+1500) < 10, result
        app.save()
        app.draw()
        root.update_idletasks()
        app.figure.savefig(ROOT/"validation"/"demo_plot.png", dpi=150)
        x, y = root.winfo_rootx(), root.winfo_rooty()
        try:
            ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(ROOT/"validation"/"ui_preview.png")
        except OSError as e:
            print("SCREENSHOT_UNAVAILABLE", str(e), flush=True)
            # Print only this application's client area, without reading the desktop.
            import ctypes
            import win32gui, win32ui
            from PIL import Image
            hwnd = root.winfo_id()
            w, h = root.winfo_width(), root.winfo_height()
            dc = win32gui.GetDC(hwnd)
            src = win32ui.CreateDCFromHandle(dc)
            dst = src.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(src, w, h)
            dst.SelectObject(bitmap)
            ok = ctypes.windll.user32.PrintWindow(hwnd, dst.GetSafeHdc(), 1)
            if ok:
                img = Image.frombuffer("RGB",(w,h),bitmap.GetBitmapBits(True),"raw","BGRX",0,1)
                if max(hi for lo,hi in img.getextrema()) > 20:
                    img.save(ROOT/"validation"/"ui_preview.png")
                    print("PRINTWINDOW_CAPTURED", flush=True)
                else:
                    print("PRINTWINDOW_EMPTY: no usable UI screenshot in this desktop session", flush=True)
            win32gui.DeleteObject(bitmap.GetHandle())
            dst.DeleteDC()
            src.DeleteDC()
            win32gui.ReleaseDC(hwnd, dc)
        print("GUI_PASS",len(app.points),"points",result, flush=True)
    except Exception as e:
        errors.append(e)
    finally:
        app.close()


root.after(19000, finish)
root.mainloop()
if errors:
    raise errors[0]
