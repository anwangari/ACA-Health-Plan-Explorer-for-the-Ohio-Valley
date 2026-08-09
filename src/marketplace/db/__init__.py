"""Database layer: schema definitions and the idempotent Parquet -> DB load."""

from marketplace.db.load import main

__all__ = ["main"]
