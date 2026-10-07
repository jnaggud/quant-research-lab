"""Generate optional macOS schedules for the historical C8/C9 monitoring workflow."""
import argparse
from pathlib import Path
import plistlib
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="install and enable the generated LaunchAgents")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "launchd/generated"
    output.mkdir(parents=True, exist_ok=True)
    for suffix, script, hour, minute in [
        ("monitor", "run_c8_monitor.sh", 16, 30),
        ("morning-summary", "run_c8_morning_summary.sh", 7, 30),
    ]:
        label = f"com.quantresearch.c8-{suffix}"
        config = {"Label": label, "WorkingDirectory": str(root),
            "ProgramArguments": ["/bin/bash", str(root / "scripts" / script)],
            "EnvironmentVariables": {"PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
                "TRADINGVIEW_CDP_PORT": os.getenv("TRADINGVIEW_CDP_PORT", "9223")},
            "StartCalendarInterval": [{"Weekday": day, "Hour": hour, "Minute": minute} for day in range(1, 6)]}
        content = plistlib.dumps(config)
        template = output / f"{label}.plist"
        template.write_bytes(content)
        print(f"Generated {template}")
        if args.install:
            if sys.platform != "darwin":
                parser.error("--install requires macOS")
            target = Path.home() / "Library/LaunchAgents" / template.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            domain = f"gui/{os.getuid()}"
            subprocess.run(["launchctl", "bootout", domain, str(target)], check=False, capture_output=True)
            subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
            print(f"Installed {label}")


if __name__ == "__main__":
    main()
