# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import concurrent.futures
import logging
import pathlib
import threading

import pytest

import ansibug.dap as dap
from ansibug._debuggee import AnsibleDebugger, DebuggeeShutdownError, _replace_root
from ansibug._logging import configure_file_logging


class WaitTrackingCondition(threading.Condition):
    """Condition that signals once the expected number of threads are waiting."""

    def __init__(self, waiters: int) -> None:
        super().__init__()
        self._remaining = waiters
        self.all_waiting = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        # The lock is held here and only released by super().wait() after the
        # waiter is registered, so a notify after all_waiting is set can't be
        # missed.
        self._remaining -= 1
        if self._remaining == 0:
            self.all_waiting.set()

        return super().wait(timeout)


def test_get_strategy_wakes_on_shutdown() -> None:
    # Bypass the Singleton so the test doesn't share state with other tests.
    debugger = type.__call__(AnsibleDebugger)
    condition = WaitTrackingCondition(waiters=1)
    debugger._strategy_connected = condition

    with concurrent.futures.ThreadPoolExecutor() as pool:
        get_fut = pool.submit(debugger._get_strategy)
        assert condition.all_waiting.wait(timeout=5)

        debugger.shutdown()

        with pytest.raises(DebuggeeShutdownError):
            get_fut.result(timeout=5)


def test_disconnect_before_strategy_releases_config_done() -> None:
    debugger = type.__call__(AnsibleDebugger)

    # Must not wait for a strategy, none can start until config done is set.
    debugger._disconnect(dap.DisconnectRequest())

    assert debugger._configuration_done.is_set()


def test_configure_file_logging_once(tmp_path: pathlib.Path) -> None:
    logger = logging.getLogger("ansibug")
    existing = list(logger.handlers)
    log_file = tmp_path / "ansibug.log"
    try:
        configure_file_logging(str(log_file), "info")
        configure_file_logging(str(log_file), "info")

        assert len(logger.handlers) == len(existing) + 1

    finally:
        for h in logger.handlers[len(existing) :]:
            logger.removeHandler(h)
            h.close()


@pytest.mark.parametrize(
    ["path", "root", "expected"],
    [
        ("/foo/main.yml", "/foo", "/new/main.yml"),
        ("/foo/main.yml", "/foo/", "/new/main.yml"),
        ("/foo", "/foo", "/new"),
        ("/foobar/main.yml", "/foo", None),
        ("/other/main.yml", "/foo", None),
        ("C:\\foo\\main.yml", "C:\\foo", "/new\\main.yml"),
        ("C:\\foobar\\main.yml", "C:\\foo", None),
    ],
)
def test_replace_root(path: str, root: str, expected: str | None) -> None:
    new_root = "/new/" if root.endswith("/") else "/new"
    assert _replace_root(path, root, new_root) == expected
