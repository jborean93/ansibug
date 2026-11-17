# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import contextlib
import threading
import typing as t

from ansibug._socket_helper import SocketCancellationToken


class SignallingCancellationToken(SocketCancellationToken):
    """Token that lets a test wait until another thread is in a cancellable call.

    Used instead of a sleep before calling cancel(). The cancel function is
    registered by the time wait_entered() returns so the cancel always reaches
    the call, whether it has blocked yet or not.
    """

    def __init__(self) -> None:
        super().__init__()
        self._entered = threading.Semaphore(0)

    @contextlib.contextmanager
    def with_cancel(
        self,
        cancel_func: t.Callable[[], None],
    ) -> collections.abc.Generator[None, None, None]:
        with super().with_cancel(cancel_func):
            self._entered.release()
            yield

    def wait_entered(self, count: int = 1, timeout: float = 10) -> None:
        """Waits for count cancellable calls to have been entered."""
        for _ in range(count):
            if not self._entered.acquire(timeout=timeout):
                raise TimeoutError("Timed out waiting for a cancellable call to start")
