Flow2API remote Windows package
Created: 2026-04-30 22:37:12
Source: H:\Code\flow2api

Included: source, docs, config, data database, .git, static assets, tests, tmp/log/test artifacts present at package time.
Excluded: .venv only. Recreate Python environment on the remote Windows machine.

Remote quick start:
  cd <unzipped folder>
  py -3.10 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install -U pip
  pip install -r requirements.txt
  python main.py
