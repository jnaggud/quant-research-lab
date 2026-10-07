"""Check public source files for accidentally included secrets and private inputs.

This is a narrow publication guard, not a complete security audit.
"""
from pathlib import Path
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', '.venv-demo', '__pycache__', '.pytest_cache',
            'node_modules', 'tradingview-mcp', 'build', 'dist', 'data', '.cache', 'cache', 'generated'}
PATTERNS = {
    'GitHub token': re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'),
    'GitHub fine-grained token': re.compile(r'github_pat_[A-Za-z0-9_]{40,}'),
    'AWS access key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential literal': re.compile(r'''(?i)(?:api[_-]?key|password|client_secret|access_token)\s*[=:]\s*["']([A-Za-z0-9_+/=.-]{20,})["']'''),
}


def source_files():
    if (ROOT / '.git').exists():
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        return [ROOT / name for name in names if name]
    found = []
    for parent, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not d.endswith('.egg-info')]
        found.extend(Path(parent) / name for name in files)
    return found


def main():
    problems = []
    files = source_files()
    for path in files:
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in rel.parts) or path.suffix in {'.parquet', '.pem', '.key'}:
            problems.append((str(rel), 'private input, dependency, or generated artifact'))
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            problems.append((str(rel), 'local environment file'))
        try:
            text = path.read_text()
        except UnicodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append((str(rel), label))
        if path.suffix == '.json':
            data = json.loads(text)
            if isinstance(data, dict) and {'bars', 'reportData', 'ordersData', 'closed_trades', 'orders'} & data.keys():
                problems.append((str(rel), 'raw market or TradingView export'))
    for path, problem in problems:
        print(f'{path}: {problem}')  # Never print matching credentials.
    if problems:
        raise SystemExit(1)
    print(f'Publication guard passed for {len(files)} files.')


if __name__ == '__main__':
    main()
