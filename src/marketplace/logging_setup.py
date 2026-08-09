"""
logging_setup.py
================
Shared logging configuration. Every stage used to repeat the same
basicConfig block; now they call get_logger(name) instead.
"""

import logging

_CONFIGURED = False


def get_logger(name):
    """Return a configured logger. Idempotent: basicConfig runs once."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(levelname)-7s  %(message)s",
            datefmt="%H:%M:%S",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
