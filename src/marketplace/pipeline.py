"""
pipeline.py
===========
End-to-end orchestration: API -> Parquet -> DB -> validation. Calls each stage's
main() in order. Lives outside the stage modules so each stage stays focused on
its one job.
"""

from marketplace.logging_setup import get_logger
from marketplace.extract import main as extract_main
from marketplace.transform import main as transform_main
from marketplace.db import main as load_main
from marketplace.validate import main as validate_main

log = get_logger("pipeline")


def run_pipeline(skip_extract=False):
    """Run the full pipeline. Returns True if validation passed."""
    if not skip_extract:
        log.info("STEP 1/4  Extracting from API ...")
        extract_main()
    else:
        log.info("STEP 1/4  Skipping extract (using existing raw_cache).")

    log.info("STEP 2/4  Transforming raw JSON -> Parquet ...")
    transform_main()

    log.info("STEP 3/4  Loading Parquet -> database ...")
    load_main()

    log.info("STEP 4/4  Running data-quality validation ...")
    ok = validate_main()
    if not ok:
        log.error("Pipeline finished but validation FAILED. Review results above.")
        return False
    log.info("Pipeline complete and validated.")
    return True
