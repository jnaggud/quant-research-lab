#!/usr/bin/env python3
"""dl_progress.py — live Databento download progress bar. NO API calls.

Reads job state from the local manifest.json and measures the real write rate from
the external volume's free-space delta (instant, no directory walk). Refreshes in
place like pip. Run it in its OWN terminal window:

    python3 scripts/dl_progress.py

Ctrl-C to quit (does NOT affect the download).
"""
import glob
import json
import os
import sys
import time

ROOT = os.getenv("DATABENTO_ROOT", "data/databento")
MAN = os.path.join(ROOT, "manifest.json")
VOL = ROOT
INTERVAL = 2.0          # seconds between samples
BAR = 42

C_G, C_D, C_C, C_Y, C_R, RST = "\033[92m", "\033[90m", "\033[96m", "\033[93m", "\033[91m", "\033[0m"


def jobs():
    try:
        m = json.load(open(MAN))
        j = m["jobs"].values()
        done = sum(1 for x in j if x["state"] == "downloaded")
        total = len(m["jobs"])
        rem_gb_est = None
        return done, total
    except Exception:
        return None, None


def free_bytes():
    try:
        s = os.statvfs(VOL)
        return s.f_bavail * s.f_frsize
    except Exception:
        return None


def active_dir_bytes():
    """(dir, total_bytes) of the newest-modified job dir — the RELIABLE download rate
    source (APFS free-space is too noisy). Returns (None, 0) if none found."""
    dirs = glob.glob(ROOT + "/mbp-1/*/") + glob.glob(ROOT + "/mbp-10/*/") + glob.glob(ROOT + "/bbo-1s/*/")
    if not dirs:
        return None, 0
    try:
        d = max(dirs, key=os.path.getmtime)
        total = sum(os.path.getsize(f) for f in glob.glob(d + "*.dbn.zst") if os.path.isfile(f))
        return d, total
    except Exception:
        return None, 0


def fmt_eta(sec):
    if sec is None or sec <= 0 or sec != sec:
        return "—"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def main():
    prev_dir, prev_bytes = active_dir_bytes()
    prev_t = time.time()
    rate_ema = 0.0
    AVG_GB = 200.0     # remaining mbp-1 jobs run ~200 GB each
    print("\033[?25l", end="")  # hide cursor
    lines_drawn = 0
    try:
        while True:
            time.sleep(INTERVAL)
            done, total = jobs()
            cur_dir, cur_bytes = active_dir_bytes()
            t = time.time()
            if done is None:
                continue
            dt = t - prev_t
            if cur_dir == prev_dir and dt > 0:            # same job -> measure growth
                inst = max(0.0, cur_bytes - prev_bytes) / dt
                rate_ema = inst if rate_ema == 0 else 0.55 * rate_ema + 0.45 * inst
            # (if the job dir changed, a job finished/started — skip this sample's rate)
            prev_dir, prev_bytes, prev_t = cur_dir, cur_bytes, t

            pct = 100.0 * done / total
            filled = int(BAR * done / total)
            bar = C_G + "█" * filled + C_D + "░" * (BAR - filled) + RST
            mbps = rate_ema / 1e6
            cur_gb = cur_bytes / 1e9
            free_gb = (free_bytes() or 0) / 1e9
            rem = total - done
            rem_gb = max(0.0, rem * AVG_GB - cur_gb)      # remaining bytes incl. rest of current job
            eta = (rem_gb * 1e3 / mbps) if mbps > 0.05 else None
            ratecol = C_G if mbps > 8 else (C_Y if mbps > 1 else C_R)

            out = [
                f"  {C_C}Databento download{RST}   {time.strftime('%H:%M:%S')}",
                f"  [{bar}] {done}/{total}  ({pct:5.1f}%)",
                f"  rate {ratecol}{mbps:6.2f} MB/s{RST}    {rem} jobs left    ETA {fmt_eta(eta)}",
                f"  current job {cur_gb:5.1f} GB (~200 GB full)    drive free {free_gb:,.0f} GB",
            ]
            if lines_drawn:
                sys.stdout.write(f"\033[{lines_drawn}A")   # move cursor up
            for ln in out:
                sys.stdout.write("\033[2K" + ln + "\n")     # clear line + write
            sys.stdout.flush()
            lines_drawn = len(out)
            if done >= total:
                print(f"\n  {C_G}✓ ALL {total} JOBS DOWNLOADED{RST}")
                break
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")   # show cursor


if __name__ == "__main__":
    main()
