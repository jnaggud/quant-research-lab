"""Keep licensed-data integration tests explicit in a public checkout."""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "test_tv_c11_exact_simulation.py": [
        "archives/c11_frozen_20260714/tv_c11_current_report_20260714.json",
        "archives/c11_frozen_20260714/tv_es1_full_15m_bars_20260714.json",
    ],
    "test_trader_metrics.py": ["archives/c11_frozen_20260714/tv_c11_current_report_20260714.json"],
}


def pytest_collection_modifyitems(items):
    for item in items:
        files = REQUIRED.get(item.path.name)
        if files:
            item.add_marker(pytest.mark.local_data)
            if not all((ROOT / name).is_file() for name in files):
                item.add_marker(pytest.mark.skip(reason="Original licensed exports are not distributed; see docs/data.md"))
