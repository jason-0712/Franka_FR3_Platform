#!/usr/bin/env python3
"""Run Mock acceptance and persist an explicit, machine-readable stage report."""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/franka_platform/acceptance_mock.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    suite = unittest.defaultTestLoader.discover(str(root/"franka_platform/tests"))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"schema_version": 1, "stage": "B", "status": "PASS" if result.wasSuccessful() else "FAIL",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": sys.version, "os": platform.platform(), "duration_s": time.monotonic()-started,
        "tests_run": result.testsRun, "failures": [str(t) for t, _ in result.failures],
        "errors": [str(t) for t, _ in result.errors], "skipped": [str(t) for t, _ in result.skipped],
        "model_packages_present": {p: importlib.util.find_spec(p) is not None for p in ("torch", "starVLA")},
        "model_packages_imported": [p for p in sys.modules if p.split('.')[0] in ("torch", "starVLA")],
        "hardware_execution": "NOT_RUN", "second_computer_migration": "NOT_RUN"}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("FRANKA_PLATFORM_MOCK="+report["status"])
    print("REPORT="+str(out.resolve()))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
