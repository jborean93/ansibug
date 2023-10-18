# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import pytest

import ansibug.dap as dap


def test_unpack_request() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "cancel",
            "arguments": {
                "requestId": None,
                "progressId": None,
            },
        }
    )

    assert isinstance(actual, dap.CancelRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.CANCEL
    assert actual.request_id is None
    assert actual.progress_id is None


def test_unpack_extra_data() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "cancel",
            "arguments": {
                "requestId": None,
                "progressId": None,
                "unknown": None,
            },
            "extra": "foo",
        }
    )

    assert isinstance(actual, dap.CancelRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.CANCEL
    assert actual.request_id is None
    assert actual.progress_id is None


def test_unpack_request_unknown_command() -> None:
    with pytest.raises(ValueError, match="Unknown DAP request command 'unknown'"):
        dap.ProtocolMessage.unpack(
            {
                "type": "request",
                "command": "unknown",
            }
        )


def test_unpack_response() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "response",
            "request_seq": 0,
            "success": True,
            "command": "launch",
        }
    )

    assert isinstance(actual, dap.LaunchResponse)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.RESPONSE
    assert actual.request_seq == 0
    assert actual.command == dap.Command.LAUNCH


def test_unpack_response_unknown_command() -> None:
    with pytest.raises(ValueError, match="Unknown DAP response command 'unknown'"):
        dap.ProtocolMessage.unpack(
            {
                "type": "response",
                "command": "unknown",
                "request_seq": 0,
                "success": True,
            }
        )


def test_unpack_event() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "event",
            "event": "stopped",
            "body": {
                "reason": "step",
            },
        }
    )

    assert isinstance(actual, dap.StoppedEvent)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.EVENT
    assert actual.event == dap.EventType.STOPPED
    assert actual.reason == dap.StoppedReason.STEP
    assert actual.description is None
    assert actual.thread_id is None
    assert actual.preserve_focus_hint is False
    assert actual.text is None
    assert actual.all_threads_stopped is False
    assert actual.hit_breakpoint_ids == []


def test_unpack_event_unknown_command() -> None:
    with pytest.raises(ValueError, match="Unknown DAP event type 'unknown'"):
        dap.ProtocolMessage.unpack(
            {
                "type": "event",
                "event": "unknown",
            }
        )


def test_unpack_error() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "response",
            "request_seq": 0,
            "success": False,
            "message": "error message",
            "command": "launch",
            "body": {
                "error": {"id": 1, "format": "detailed error"},
            },
        }
    )

    assert isinstance(actual, dap.ErrorResponse)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.RESPONSE
    assert actual.request_seq == 0
    assert actual.command == dap.Command.LAUNCH
    assert actual.message == "error message"
    assert isinstance(actual.error, dap.Message)
    assert actual.error.id == 1
    assert actual.error.format == "detailed error"


def test_unpack_unknown_message_type() -> None:
    with pytest.raises(ValueError, match="Unknown DAP message type 'unknown'"):
        dap.ProtocolMessage.unpack({"type": "unknown"})


def test_unpack_unset_prop() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "disconnect",
            "arguments": {},
        }
    )

    assert isinstance(actual, dap.DisconnectRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.DISCONNECT
    assert actual.restart is False
    assert actual.terminate_debuggee is None
    assert actual.suspend_debuggee is False


def test_unpack_none_prop() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "disconnect",
            "arguments": {
                "restart": None,
                "terminateDebuggee": False,
                "suspendDebuggee": None,
            },
        }
    )

    assert isinstance(actual, dap.DisconnectRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.DISCONNECT
    assert actual.restart is False
    assert actual.terminate_debuggee is False
    assert actual.suspend_debuggee is False


def test_unpack_list_value_basic() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "runInTerminal",
            "arguments": {
                "args": [
                    "arg1",
                    "arg2",
                ],
                "env": {
                    "env1": "value1",
                    "env2": "value2",
                },
            },
        }
    )

    assert isinstance(actual, dap.RunInTerminalRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.RUN_IN_TERMINAL
    assert actual.kind == "integrated"
    assert actual.title is None
    assert actual.cwd == ""
    assert actual.args == ["arg1", "arg2"]
    assert actual.env == {"env1": "value1", "env2": "value2"}


def test_unpack_list_value_complex() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 1,
            "type": "request",
            "command": "setBreakpoints",
            "arguments": {
                "source": {
                    "name": "source",
                    "path": "/tmp/test.txt",
                },
                "breakpoints": [
                    {
                        "line": 1,
                        "column": 0,
                        "condition": "my condition",
                    },
                    {
                        "line": 2,
                        "column": 0,
                        "logMessage": "my message",
                    },
                ],
            },
        }
    )

    assert isinstance(actual, dap.SetBreakpointsRequest)
    assert actual.seq == 1
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.SET_BREAKPOINTS
    assert isinstance(actual.source, dap.Source)
    assert actual.source.name == "source"
    assert actual.source.path == "/tmp/test.txt"
    assert actual.source.source_reference == 0
    assert actual.source.presentation_hint == "normal"
    assert actual.source.origin is None
    assert actual.source.sources == []
    assert actual.source.adapter_data is None
    assert actual.source.checksums == []
    assert len(actual.breakpoints) == 2
    assert actual.breakpoints[0].line == 1
    assert actual.breakpoints[0].column == 0
    assert actual.breakpoints[0].condition == "my condition"
    assert actual.breakpoints[0].hit_condition is None
    assert actual.breakpoints[0].log_message is None
    assert actual.breakpoints[1].line == 2
    assert actual.breakpoints[1].column == 0
    assert actual.breakpoints[1].condition is None
    assert actual.breakpoints[1].hit_condition is None
    assert actual.breakpoints[1].log_message == "my message"
    assert actual.lines == []
    assert actual.source_modified is False
