"""
runner.py
=========
Runs every check against the loaded database, logs each result, and writes a
validation_results table to Parquet so the run is auditable. Returns True if no
ERROR-level check failed (the caller maps this to an exit code).
"""

from sqlalchemy import create_engine, event

from marketplace import config
from marketplace.logging_setup import get_logger
from marketplace.validate.checks import CHECKS, Results

log = get_logger("validate")


def main(database_url=None):
    database_url = database_url or config.DATABASE_URL
    if not database_url:
        raise RuntimeError("No DATABASE_URL set. Add it to your .env file.")

    log.info("Running data-quality validation against %s", database_url.split("@")[-1])
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    res = Results()
    with engine.connect() as conn:
        for check in CHECKS:
            check(conn, res)

    df = res.to_frame()
    out = config.TIDY_DIR / "validation_results.parquet"
    df.to_parquet(out, index=False, engine="pyarrow")

    n_fail = len(df[df["status"] == "FAIL"])
    n_err = len(res.failed_errors())
    log.info("-" * 60)
    log.info("Validation summary: %d checks, %d passed, %d failed (%d ERROR).",
             len(df), len(df) - n_fail, n_fail, n_err)
    log.info("Results written to %s", out)

    if n_err:
        log.error("VALIDATION FAILED — %d error-level check(s) did not pass.", n_err)
        return False
    log.info("VALIDATION PASSED.")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
