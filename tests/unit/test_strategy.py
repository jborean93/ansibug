# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import itertools
import typing as t
from unittest.mock import MagicMock

import ansibug.dap
from ansibug.ansible_collections.ansibug.dap.plugins.strategy.debug import (
    AnsibleDebugState,
    AnsibleStackFrame,
    AnsibleThread,
)


def test_exit_threads_removes_stackframes() -> None:
    state = AnsibleDebugState(MagicMock(), MagicMock(), MagicMock())
    host = MagicMock()
    thread = state.threads[2] = state._host_threads[host] = AnsibleThread(id=2, host=host)
    for sfid in [1, 2]:
        state.stackframes[sfid] = AnsibleStackFrame(id=sfid, task=MagicMock(), task_vars={}, debugger=MagicMock())
        thread.stack_frames.insert(0, sfid)
    state.stackframes[2].variables.append(10)
    state.variables[10] = MagicMock()

    state.exit_threads()

    assert list(state.threads) == [1]
    assert state._host_threads == {}
    assert state.stackframes == {}
    assert state.variables == {}


def test_continue_exited_thread() -> None:
    state = AnsibleDebugState(MagicMock(), MagicMock(), MagicMock())

    # The client can still reference a thread that has since exited.
    state.continue_request(ansibug.dap.ContinueRequest(thread_id=99, single_thread=True))

    assert list(state.threads) == [1]


class RecordingDict(dict[str, t.Any]):
    """Records each key read, like HostVars templating each value on access."""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.read: list[str] = []

    def __getitem__(self, key: str) -> t.Any:
        self.read.append(key)
        return super().__getitem__(key)


def _state_with_frame(task_vars: dict[str, t.Any]) -> tuple[AnsibleDebugState, AnsibleStackFrame]:
    debugger = MagicMock()
    debugger.next_variable_id.side_effect = itertools.count(1).__next__
    state = AnsibleDebugState(debugger, MagicMock(), MagicMock())

    task = MagicMock()
    task.args = {"opt": "value"}
    sf = state.stackframes[1] = AnsibleStackFrame(id=1, task=task, task_vars=task_vars, debugger=debugger)

    return state, sf


def test_scopes_created_once_and_hostvars_lazy() -> None:
    inventory_hostvars = RecordingDict(host_var="foo")
    state, _ = _state_with_frame(
        {
            "inventory_hostname": "host1",
            "hostvars": {"host1": inventory_hostvars},
            "vars": {},
        }
    )

    scopes = state.get_scopes(ansibug.dap.ScopesRequest(frame_id=1)).scopes
    var_count = len(state.variables)
    assert inventory_hostvars.read == []

    # Selecting the frame again reuses the same variables.
    scopes2 = state.get_scopes(ansibug.dap.ScopesRequest(frame_id=1)).scopes
    assert [s.variables_reference for s in scopes2] == [s.variables_reference for s in scopes]
    assert len(state.variables) == var_count

    host_scope = next(s for s in scopes if s.name == "Host Variables")
    host_vars = state.get_variables(ansibug.dap.VariablesRequest(variables_reference=host_scope.variables_reference))
    assert inventory_hostvars.read == ["host_var"]
    assert "host_var" in [v.name for v in host_vars.variables]


def test_variables_reuse_children() -> None:
    state, sf = _state_with_frame({"my_dict": {"key": "value"}, "my_bytes": b"abc"})
    var_id = state._add_variable(sf, sf.task_vars).id

    def get() -> dict[str, ansibug.dap.Variable]:
        resp = state.get_variables(ansibug.dap.VariablesRequest(variables_reference=var_id))
        return {v.name: v for v in resp.variables}

    first = get()
    second = get()

    assert first["my_dict"].variables_reference != 0
    assert second["my_dict"].variables_reference == first["my_dict"].variables_reference
    # bytes is a Sequence but shouldn't be expanded into ints.
    assert first["my_bytes"].variables_reference == 0
