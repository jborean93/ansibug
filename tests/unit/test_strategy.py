# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import itertools
import typing as t
from unittest.mock import MagicMock

import pytest

import ansibug.dap
from ansibug._playbook._debug_state import (
    AnsibleDebugState,
    AnsibleStackFrame,
    AnsibleThread,
    _resolve_raw_path,
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
    task.copy.return_value = task
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


class TemplatingDict(dict[str, t.Any]):
    """Like a Data Tagging lazy container that templates a value on access."""

    def __getitem__(self, key: str) -> t.Any:
        raise AssertionError("templated")


class NotADict(collections.abc.Mapping[str, t.Any]):
    """Like HostVars, a Mapping that templates on access."""

    def __getitem__(self, key: str) -> t.Any:
        raise AssertionError("templated")

    def __iter__(self) -> collections.abc.Iterator[str]:
        return iter(["host1"])

    def __len__(self) -> int:
        return 1


@pytest.mark.parametrize(
    ["expression", "expected"],
    [
        ("foo", {"bar": [1, "{{ raw }}"]}),
        (" foo ", {"bar": [1, "{{ raw }}"]}),
        ("foo.bar", [1, "{{ raw }}"]),
        ("foo['bar'][1]", "{{ raw }}"),
        ('foo["bar"][0]', 1),
        ("lazy.value", "{{ not templated }}"),
    ],
)
def test_resolve_raw_path(expression: str, expected: t.Any) -> None:
    variables = {
        "foo": {"bar": [1, "{{ raw }}"]},
        "lazy": TemplatingDict(value="{{ not templated }}"),
    }

    assert _resolve_raw_path(expression, variables) == expected


@pytest.mark.parametrize(
    "expression",
    ["missing", "foo.missing", "foo.bar[5]", "foo + 1", "lookup('pipe', 'id')", "hostvars.host1", "{{ foo }}", ""],
)
def test_resolve_raw_path_invalid(expression: str) -> None:
    variables = {"foo": {"bar": [1]}, "hostvars": NotADict()}

    with pytest.raises((KeyError, IndexError)):
        _resolve_raw_path(expression, variables)


@pytest.mark.parametrize(
    ["text", "prefix", "expected"],
    [
        ("!s", "s", ["set_hostvar", "set_option", "sh", "so"]),
        ("!", "", ["remove_option", "ro", "set_hostvar", "set_option", "sh", "so", "t", "template"]),
        ("!so o", "o", ["opt"]),
        ("!ro ", "", ["opt"]),
        ("inv", "inv", ["inventory_hostname"]),
        ("{{ my", "my", ["my_dict"]),
        ("!sh inv", "inv", ["inventory_hostname"]),
    ],
)
def test_completions(text: str, prefix: str, expected: list[str]) -> None:
    state, _ = _state_with_frame({"inventory_hostname": "host1", "my_dict": {}})

    resp = state.completions(ansibug.dap.CompletionsRequest(text=text, column=len(text) + 1, frame_id=1))

    assert [c.label for c in resp.targets] == expected
    # The prefix before the cursor is replaced, start is a 0 based offset as VS Code expects.
    assert {(c.start, c.length) for c in resp.targets} == {(len(text) - len(prefix), len(prefix))}


def test_variables_evaluate_name() -> None:
    inventory_hostvars = RecordingDict(host_var="foo")
    state, _ = _state_with_frame(
        {
            "inventory_hostname": "host1",
            "hostvars": {"host1": inventory_hostvars},
            "vars": {"play-var": 1},
            "my_dict": {"key": [{"nested": 1}]},
            "not-identifier": 1,
        }
    )
    scopes = {s.name: s.variables_reference for s in state.get_scopes(ansibug.dap.ScopesRequest(frame_id=1)).scopes}

    def evaluate_names(variables_reference: int) -> dict[str, str | None]:
        resp = state.get_variables(ansibug.dap.VariablesRequest(variables_reference=variables_reference))
        return {v.name: v.evaluate_name for v in resp.variables}

    def child(variables_reference: int, name: str) -> int:
        resp = state.get_variables(ansibug.dap.VariablesRequest(variables_reference=variables_reference))
        return next(v.variables_reference for v in resp.variables if v.name == name)

    task_vars = scopes["Task Variables"]
    assert evaluate_names(task_vars)["my_dict"] == "my_dict"
    assert evaluate_names(task_vars)["not-identifier"] is None
    my_dict = child(task_vars, "my_dict")
    assert evaluate_names(my_dict) == {"key": "my_dict['key']"}
    key_list = child(my_dict, "key")
    assert evaluate_names(key_list) == {"0": "my_dict['key'][0]"}
    assert evaluate_names(child(key_list, "0")) == {"nested": "my_dict['key'][0]['nested']"}

    host_vars = evaluate_names(scopes["Host Variables"])
    assert host_vars["host_var"] == "hostvars[inventory_hostname]['host_var']"
    # Task vars overlaid on the host vars are not in hostvars.
    assert host_vars["my_dict"] == "my_dict"

    assert evaluate_names(scopes["Global Variables"]) == {"play-var": "vars['play-var']"}
    assert evaluate_names(scopes["Module Options"]) == {"opt": None}


@pytest.mark.parametrize(
    ["filter", "start", "count", "expected"],
    [
        (None, None, None, [str(i) for i in range(10)]),
        (None, 2, 3, ["2", "3", "4"]),
        ("indexed", 8, None, ["8", "9"]),
        ("named", None, None, []),
    ],
)
def test_variables_paging(filter: t.Any, start: int | None, count: int | None, expected: list[str]) -> None:
    state, sf = _state_with_frame({})
    var = state._add_variable(sf, list(range(10)))

    resp = state.get_variables(
        ansibug.dap.VariablesRequest(variables_reference=var.id, filter=filter, start=start, count=count)
    )

    assert [v.name for v in resp.variables] == expected


@pytest.mark.parametrize("supported", [True, False])
def test_repl_invalidates_variables(supported: bool) -> None:
    state, _ = _state_with_frame({"inventory_hostname": "host1", "hostvars": {"host1": {}}, "vars": {}})
    debugger = t.cast(MagicMock, state._debugger)
    debugger.supports_invalidated_event = supported

    state.evaluate(ansibug.dap.EvaluateRequest(expression="!so opt 'new'", frame_id=1, context="repl"))
    state.evaluate(ansibug.dap.EvaluateRequest(expression="!t 1", frame_id=1, context="repl"))

    sent = [c.args[0] for c in debugger.queue_msg.call_args_list]
    invalidated = [m for m in sent if isinstance(m, ansibug.dap.InvalidatedEvent)]
    assert [m.areas for m in invalidated] == ([["variables"]] if supported else [])


def test_completions_detail() -> None:
    state, sf = _state_with_frame(
        {
            "inventory_hostname": "host1",
            "my_dict": {"a": 1, "b": 2},
            "long": "x" * 100,
            "lazy": TemplatingDict(value="{{ not templated }}"),
            "hostvars": NotADict(),
        }
    )
    sf.task.args = {"opt": "{{ raw }}"}

    def details(text: str) -> dict[str, str | None]:
        resp = state.completions(ansibug.dap.CompletionsRequest(text=text, column=len(text) + 1, frame_id=1))
        return {c.label: c.detail for c in resp.targets}

    assert details("!se") == {
        "set_hostvar": "!set_hostvar <name> <expression>: Set a host variable.",
        "set_option": "!set_option <name> <expression>: Set a module option.",
    }
    assert details("!so") == {"so": "!so <name> <expression>: Set a module option."}
    assert details("!so ") == {"opt": "str: '{{ raw }}'"}

    task_vars = details("")
    assert task_vars["inventory_hostname"] == "str: 'host1'"
    assert task_vars["my_dict"] == "dict (2 items)"
    assert task_vars["long"] == f"str: '{'x' * 46}..."
    # Only the size of a container is used so it isn't templated.
    assert task_vars["lazy"] == "dict (1 items)"
    # Other types like hostvars only show their type.
    assert task_vars["hostvars"] == "dict"
