# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import ansibug.dap as dap


def test_breakpoint_event_pack() -> None:
    msg = dap.BreakpointEvent(
        reason="value",
        breakpoint=dap.Breakpoint(),
    )
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.EVENT,
        "event": dap.EventType.BREAKPOINT,
        "body": {
            "reason": "value",
            "breakpoint": dap.Breakpoint(),
        },
    }


def test_breakpoint_event_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "event",
            "event": "breakpoint",
            "body": {
                "reason": "value",
                "breakpoint": {
                    "id": None,
                    "verified": False,
                    "message": None,
                    "source": None,
                    "line": None,
                    "column": None,
                    "endLine": None,
                    "endColumn": None,
                    "instructionReference": None,
                    "offset": None,
                },
            },
        }
    )

    assert isinstance(actual, dap.BreakpointEvent)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.EVENT
    assert actual.event == dap.EventType.BREAKPOINT
    assert actual.reason == "value"
    assert actual.breakpoint.id is None
    assert actual.breakpoint.verified is False
    assert actual.breakpoint.message is None
    assert actual.breakpoint.source is None
    assert actual.breakpoint.line is None
    assert actual.breakpoint.column is None
    assert actual.breakpoint.end_line is None
    assert actual.breakpoint.end_column is None
    assert actual.breakpoint.instruction_reference is None
    assert actual.breakpoint.offset is None
