# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import threading

import pytest

import ansibug.dap as dap
from ansibug._debuggee import (
    AnsibleDebugger,
    DebugConfiguration,
    DebuggeeShutdownError,
    PlaybookProcessInfo,
    _replace_root,
    parse_hit_condition,
)


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
    debugger = AnsibleDebugger()
    condition = WaitTrackingCondition(waiters=1)
    debugger._strategy_connected = condition

    with concurrent.futures.ThreadPoolExecutor() as pool:
        get_fut = pool.submit(debugger._get_strategy)
        assert condition.all_waiting.wait(timeout=5)

        debugger.shutdown()

        with pytest.raises(DebuggeeShutdownError):
            get_fut.result(timeout=5)


def test_initialized_waits_for_playbook_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    debugger = AnsibleDebugger()
    sent: list[dap.ProtocolMessage | None] = []
    monkeypatch.setattr(debugger, "queue_msg", sent.append)
    config_msg = dap.OutputEvent(
        category=DebugConfiguration.OUTPUT_CATEGORY,
        output="",
        data=DebugConfiguration().to_json(),
    )

    # The client is only asked for breakpoints once they can be validated.
    debugger.process_message(config_msg)
    assert sent == []

    debugger.playbook_loaded(None)
    assert [type(m) for m in sent] == [dap.InitializedEvent]

    # A later playbook only registers its breakpoints.
    debugger.playbook_loaded(None)
    assert len(sent) == 1


def test_initialized_after_playbook_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    debugger = AnsibleDebugger()
    sent: list[dap.ProtocolMessage | None] = []
    monkeypatch.setattr(debugger, "queue_msg", sent.append)

    # A client that attaches after the playbook loaded is initialized as soon
    # as the adapter sends the debug config.
    debugger.playbook_loaded(None)
    assert sent == []

    debugger.process_message(
        dap.OutputEvent(
            category=DebugConfiguration.OUTPUT_CATEGORY,
            output="",
            data=DebugConfiguration().to_json(),
        )
    )
    assert [type(m) for m in sent] == [dap.InitializedEvent]


def test_playbook_loaded_updates_pid_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    debugger = AnsibleDebugger()
    monkeypatch.setattr(debugger, "queue_msg", lambda m: None)
    debugger._proc_info = PlaybookProcessInfo(pid=1, address="addr", use_tls=False, playbook_file=None)
    debugger._write_pid_file(debugger._proc_info)
    pid_file = debugger._proc_pid_file
    assert json.loads(pid_file.read_text())["playbook_file"] is None

    debugger.playbook_loaded("/tmp/main.yml")

    assert json.loads(pid_file.read_text())["playbook_file"] == "/tmp/main.yml"
    # The temp file used for the atomic replace is gone.
    assert [p.name for p in tmp_path.iterdir()] == [pid_file.name]


def test_disconnect_before_strategy_releases_config_done() -> None:
    debugger = AnsibleDebugger()

    # Must not wait for a strategy, none can start until config done is set.
    debugger._disconnect(dap.DisconnectRequest())

    assert debugger._configuration_done.is_set()


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


@pytest.mark.parametrize(
    ["condition", "hits_that_stop"],
    [
        ("2", [2]),
        ("==2", [2]),
        (" > 2 ", [3, 4, 5, 6]),
        (">=2", [2, 3, 4, 5, 6]),
        ("<3", [1, 2]),
        ("<=3", [1, 2, 3]),
        ("%3", [3, 6]),
    ],
)
def test_parse_hit_condition(condition: str, hits_that_stop: list[int]) -> None:
    check = parse_hit_condition(condition)

    assert check is not None
    assert [h for h in range(1, 7) if check(h)] == hits_that_stop


@pytest.mark.parametrize("condition", ["", "abc", "=2", "2.5", "%0", ">=-1"])
def test_parse_hit_condition_invalid(condition: str) -> None:
    assert parse_hit_condition(condition) is None


def test_exit_keeps_exception_when_shutdown_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    debugger = AnsibleDebugger()

    def shutdown() -> None:
        raise PermissionError("pid file")

    monkeypatch.setattr(debugger, "shutdown", shutdown)

    # The playbook's exit code wins over a failure to clean up.
    with pytest.raises(SystemExit) as exc:
        with debugger:
            raise SystemExit(2)

    assert exc.value.code == 2
    assert "Failed to shutdown the debugger" in caplog.text
