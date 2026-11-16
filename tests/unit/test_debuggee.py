# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import concurrent.futures
import threading

import pytest

import ansibug.dap as dap
from ansibug._debuggee import AnsibleDebugger, DebuggeeShutdownError


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
    condition = WaitTrackingCondition(waiters=2)
    debugger._strategy_connected = condition

    with concurrent.futures.ThreadPoolExecutor() as pool:
        get_fut = pool.submit(debugger._get_strategy)
        disconnect_fut = pool.submit(debugger._disconnect, dap.DisconnectRequest())
        assert condition.all_waiting.wait(timeout=5)

        debugger.shutdown()

        with pytest.raises(DebuggeeShutdownError):
            get_fut.result(timeout=5)

        # A disconnect with no strategy is a no-op rather than an error.
        assert disconnect_fut.result(timeout=5) is None
