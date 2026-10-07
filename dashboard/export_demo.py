"""Export the synthetic studio as a static site with no server or credentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from dashboard.demo import live_payload, synthetic_report
from dashboard.trader_metrics import summarize_report


def export_site(output: Path) -> None:
    """Write only public assets and freshly generated synthetic payloads."""
    studio = Path(__file__).resolve().parent / "studio"
    output = output.resolve()
    if output == studio or studio in output.parents:
        raise ValueError("Export into a separate directory, not the studio source.")
    assets = output / "studio-assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ("studio.css", "studio.js"):
        shutil.copyfile(studio / name, assets / name)
    html = (studio / "index.html").read_text()
    html = html.replace('<html lang="en">', '<html lang="en" data-live-url="./fixtures/live.json" data-trader-url="./fixtures/trader.json">')
    html = html.replace('"/studio-assets/', '"./studio-assets/')
    (output / "index.html").write_text(html)
    fixtures = output / "fixtures"
    fixtures.mkdir(exist_ok=True)
    report = synthetic_report()
    payloads = {
        "live": live_payload(),
        "trader": {"ok": True, "live": False, "demo": True,
                   "source": "Synthetic ledger · illustrative results",
                   "strategy": report["source"]["name"], **summarize_report(report)},
    }
    for name, payload in payloads.items():
        (fixtures / f"{name}.json").write_text(json.dumps(payload, allow_nan=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_site(args.output)
    print(f"Synthetic demo exported to {args.output.resolve()}")


if __name__ == "__main__":
    main()
