#!/usr/bin/env python
"""
Convenience test runner for Movie Analytics Dashboard.
Runs the full pytest suite with coverage reporting.

Usage:
    python run_tests.py              # Run all tests
    python run_tests.py -v           # Verbose output
    python run_tests.py -x           # Stop on first failure
    python run_tests.py -k auth      # Run tests matching 'auth'
    python run_tests.py --no-cov     # Skip coverage report
"""
import sys

import pytest


def main():
    args = sys.argv[1:]

    # pytest.ini already sets coverage flags and --tb=short.
    # Just pass through any extra args the user provided.
    default_args = ["tests/"]

    # Allow --no-cov to skip coverage (overrides pytest.ini addopts)
    if "--no-cov" in args:
        args.remove("--no-cov")
        default_args = ["tests/", "--no-cov"]

    exit_code = pytest.main(default_args + args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
