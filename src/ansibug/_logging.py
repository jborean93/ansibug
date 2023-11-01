# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import logging
import typing as t

LogLevel = t.Literal["info", "debug", "warning", "error"]

DEFAULT_FORMAT = "%(asctime)s | %(name)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s"


def configure_file_logging(
    file: str,
    level: LogLevel,
    format: str | None = None,
) -> None:
    """Configures the ansibug logger for file logging.

    Configures the file logging config for the ansibug logger.

    Args:
        file: The log file to log to.
        level: The log level to set.
        format: A custom format to use for the log messages.
    """
    log_level = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }[level]

    fh = logging.FileHandler(file, mode="a", encoding="utf-8")
    fh.setLevel(log_level)
    fh.setFormatter(logging.Formatter(format or DEFAULT_FORMAT))

    ansibug_logger = logging.getLogger("ansibug")
    ansibug_logger.setLevel(log_level)
    ansibug_logger.addHandler(fh)
