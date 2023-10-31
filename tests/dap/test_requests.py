# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import ansibug.dap as dap


def test_attach_request_pack() -> None:
    msg = dap.AttachRequest(
        arguments={
            "type": "attach",
            "foo": "bar",
        },
        restart="any value",
    )
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.REQUEST,
        "command": dap.Command.ATTACH,
        "arguments": {
            "__restart": "any value",
            "type": "attach",
            "foo": "bar",
        },
    }


def test_attach_request_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "request",
            "command": "attach",
            "arguments": {
                "__restart": "any value",
                "type": "attach",
                "foo": "bar",
            },
        }
    )

    assert isinstance(actual, dap.AttachRequest)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.ATTACH
    assert actual.restart == "any value"
    assert actual.arguments == {
        "type": "attach",
        "foo": "bar",
    }


def test_launch_request_pack() -> None:
    msg = dap.LaunchRequest(
        arguments={
            "type": "launch",
            "foo": "bar",
        },
        no_debug=True,
        restart="any value",
    )
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.REQUEST,
        "command": dap.Command.LAUNCH,
        "arguments": {
            "noDebug": True,
            "__restart": "any value",
            "type": "launch",
            "foo": "bar",
        },
    }


def test_launch_request_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "request",
            "command": "launch",
            "arguments": {
                "noDebug": True,
                "__restart": "any value",
                "type": "launch",
                "foo": "bar",
            },
        }
    )

    assert isinstance(actual, dap.LaunchRequest)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.REQUEST
    assert actual.command == dap.Command.LAUNCH
    assert actual.no_debug is True
    assert actual.restart == "any value"
    assert actual.arguments == {
        "type": "launch",
        "foo": "bar",
    }
