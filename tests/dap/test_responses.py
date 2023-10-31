# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import ansibug.dap as dap


def test_cancel_response_pack() -> None:
    msg = dap.CancelResponse(request_seq=1)
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.RESPONSE,
        "request_seq": 1,
        "success": True,
        "command": dap.Command.CANCEL,
    }


def test_cancel_response_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "response",
            "request_seq": 1,
            "success": True,
            "command": "cancel",
        }
    )

    assert isinstance(actual, dap.CancelResponse)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.RESPONSE
    assert actual.request_seq == 1
    assert actual.success
    assert actual.command == dap.Command.CANCEL


def test_configuration_done_response_pack() -> None:
    msg = dap.ConfigurationDoneResponse(request_seq=1)
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.RESPONSE,
        "request_seq": 1,
        "success": True,
        "command": dap.Command.CONFIGURATION_DONE,
    }


def test_configuration_done_response_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "response",
            "request_seq": 1,
            "success": True,
            "command": "configurationDone",
        }
    )

    assert isinstance(actual, dap.ConfigurationDoneResponse)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.RESPONSE
    assert actual.request_seq == 1
    assert actual.success
    assert actual.command == dap.Command.CONFIGURATION_DONE


def test_continue_done_response_pack() -> None:
    msg = dap.ContinueResponse(request_seq=1)
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.RESPONSE,
        "request_seq": 1,
        "success": True,
        "command": dap.Command.CONTINUE,
        "body": {
            "allThreadsContinued": True,
        },
    }


def test_continue_done_response_unpack() -> None:
    actual = dap.ProtocolMessage.unpack(
        {
            "seq": 0,
            "type": "response",
            "request_seq": 1,
            "success": True,
            "command": "continue",
            "body": {
                "allThreadsContinued": True,
            },
        }
    )

    assert isinstance(actual, dap.ContinueResponse)
    assert actual.seq == 0
    assert actual.message_type == dap.MessageType.RESPONSE
    assert actual.request_seq == 1
    assert actual.success
    assert actual.command == dap.Command.CONTINUE
    assert actual.all_threads_continued


def test_error_response_pack_no_error() -> None:
    msg = dap.ErrorResponse(
        command=dap.Command.LAUNCH,
        request_seq=1,
        message="error message",
    )
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.RESPONSE,
        "request_seq": 1,
        "success": False,
        "command": dap.Command.LAUNCH,
        "message": "error message",
        "body": {"error": None},
    }


def test_error_response_pack_with_error() -> None:
    msg = dap.ErrorResponse(
        command=dap.Command.LAUNCH,
        request_seq=1,
        message="error message",
        error=dap.Message(
            id=1,
            format="detailed error",
        ),
    )
    actual = msg.pack()

    assert actual == {
        "seq": 0,
        "type": dap.MessageType.RESPONSE,
        "request_seq": 1,
        "success": False,
        "command": dap.Command.LAUNCH,
        "message": "error message",
        "body": {
            "error": dap.Message(
                id=1,
                format="detailed error",
            ),
        },
    }
