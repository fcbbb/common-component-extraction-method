#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
d = ROOT
while d != d.parent:
    if (d / "shared" / "harness" / "run_task.py").is_file():
        sys.path.insert(0, str(d))
        break
    d = d.parent
from shared.harness.run_task import main
raise SystemExit(main())
