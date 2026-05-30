"""
__main__.py
===========
Command-line entry point: `python -m marketplace [stage] [--no-extract]`.

  python -m marketplace                full pipeline (fresh API pull)
  python -m marketplace --no-extract   reuse cached JSON, skip the API pull
  python -m marketplace extract        run a single stage
  python -m marketplace transform
  python -m marketplace load
  python -m marketplace validate
  python -m marketplace dashboard      launch the Dash app
"""

import sys
import argparse

from marketplace.pipeline import run_pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(prog="marketplace", description=__doc__)
    parser.add_argument(
        "stage", nargs="?", default="pipeline",
        choices=["pipeline", "extract", "transform", "load", "validate", "dashboard"],
        help="which stage to run (default: full pipeline)",
    )
    parser.add_argument(
        "--no-extract", action="store_true",
        help="reuse cached JSON instead of pulling from the API (pipeline only)",
    )
    args = parser.parse_args(argv)

    if args.stage == "pipeline":
        ok = run_pipeline(skip_extract=args.no_extract)
        return 0 if ok else 1

    if args.stage == "extract":
        from marketplace.extract import main as run
    elif args.stage == "transform":
        from marketplace.transform import main as run
    elif args.stage == "load":
        from marketplace.db import main as run
    elif args.stage == "validate":
        from marketplace.validate import main as run
    elif args.stage == "dashboard":
        from marketplace.dashboard.app import main as run

    result = run()
    # validate returns a bool; map False -> exit 1. Other stages return None.
    return 1 if result is False else 0


if __name__ == "__main__":
    sys.exit(main())
