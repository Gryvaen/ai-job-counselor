"""Central logging configuration."""

import logging
import sys

from config.settings import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
