# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from unittest.mock import MagicMock

import ansibug.dap
from ansibug.ansible_collections.ansibug.dap.plugins.strategy.debug import (
    AnsibleDebugState,
    AnsibleStackFrame,
    AnsibleThread,
)


def test_exit_threads_removes_stackframes() -> None:
    state = AnsibleDebugState(MagicMock(), MagicMock(), MagicMock())
    thread = state.threads[2] = AnsibleThread(id=2, host=MagicMock())
    for sfid in [1, 2]:
        state.stackframes[sfid] = AnsibleStackFrame(id=sfid, task=MagicMock(), task_vars={}, debugger=MagicMock())
        thread.stack_frames.insert(0, sfid)
    state.stackframes[2].variables.append(10)
    state.variables[10] = MagicMock()

    state.exit_threads()

    assert list(state.threads) == [1]
    assert state.stackframes == {}
    assert state.variables == {}


def test_continue_exited_thread() -> None:
    state = AnsibleDebugState(MagicMock(), MagicMock(), MagicMock())

    # The client can still reference a thread that has since exited.
    state.continue_request(ansibug.dap.ContinueRequest(thread_id=99, single_thread=True))

    assert list(state.threads) == [1]
