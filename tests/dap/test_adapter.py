# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import json

import pytest

import ansibug.dap as dap


def test_connection_no_data() -> None:
    conn = dap.DebugAdapterConnection()
    conn.data_to_send() == b""
    conn.data_to_send(n=10) == b""


def test_connection_all_data() -> None:
    msg = dap.InitializeRequest(
        adapter_id="Ansibug DAP",
        client_id="My Client",
        supports_variable_type=True,
    )
    conn = dap.DebugAdapterConnection()
    conn.queue_msg(msg)

    data = conn.data_to_send()
    data_idx = data.index(b"\r\n\r\n")
    header = data[:data_idx]
    value = data[data_idx + 4 :]

    assert header == f"Content-Length: {len(value)}".encode()
    actual = json.loads(value.decode())

    assert actual == {
        "seq": 1,
        "type": "request",
        "command": "initialize",
        "arguments": {
            "clientID": "My Client",
            "clientName": None,
            "adapterID": "Ansibug DAP",
            "locale": None,
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "pathFormat": "path",
            "supportsVariableType": True,
            "supportsVariablePaging": False,
            "supportsRunInTerminalRequest": False,
            "supportsMemoryReferences": False,
            "supportsProgressReporting": False,
            "supportsInvalidatedEvent": False,
            "supportsMemoryEvent": False,
        },
    }

    assert conn.data_to_send() == b""

    conn.queue_msg(
        dap.RunInTerminalRequest(
            kind="external",
            title="Debug Title",
            args=["python", "-m", "ansible"],
        )
    )

    data = conn.data_to_send()
    data_idx = data.index(b"\r\n\r\n")
    header = data[:data_idx]
    value = data[data_idx + 4 :]

    actual = json.loads(value.decode())

    assert actual == {
        "seq": 2,
        "type": "request",
        "command": "runInTerminal",
        "arguments": {
            "kind": "external",
            "title": "Debug Title",
            "cwd": "",
            "args": ["python", "-m", "ansible"],
            "env": {},
        },
    }


def test_connection_send_partial_data() -> None:
    msg = dap.SetBreakpointsRequest(
        source=dap.Source(
            name="Source",
            path="/tmp/test.txt",
        ),
        breakpoints=[
            dap.SourceBreakpoint(line=0),
        ],
    )
    conn = dap.DebugAdapterConnection()
    conn.queue_msg(msg)

    data = conn.data_to_send(n=10)

    assert data == b"Content-Le"

    data = conn.data_to_send()
    data_idx = data.index(b"\r\n\r\n")
    header = data[:data_idx]
    value = data[data_idx + 4 :]

    assert header == f"ngth: {len(value)}".encode()
    actual = json.loads(value.decode())

    assert actual == {
        "seq": 1,
        "type": "request",
        "command": "setBreakpoints",
        "arguments": {
            "source": {
                "name": "Source",
                "path": "/tmp/test.txt",
                "sourceReference": 0,
                "presentationHint": "normal",
                "origin": None,
                "sources": [],
                "adapterData": None,
                "checksums": [],
            },
            "breakpoints": [
                {
                    "line": 0,
                    "column": None,
                    "condition": None,
                    "hitCondition": None,
                    "logMessage": None,
                },
            ],
            "lines": [],
            "sourceModified": False,
        },
    }


def test_receive_without_content_length() -> None:
    conn = dap.DebugAdapterConnection()
    conn.receive_data(b"Content-Type: application/json\r\n\r\n")

    expected = "Expected Content-Length header before message payload but none found"
    with pytest.raises(ValueError, match=expected):
        conn.next_message()


def test_receive_out_of_sequence() -> None:
    client = dap.DebugAdapterConnection()
    client.queue_msg(
        dap.InitializeRequest(
            adapter_id="Ansibug DAP",
            client_id="My Client",
            supports_variable_type=True,
        )
    )
    client.data_to_send()
    client.queue_msg(dap.LaunchRequest(arguments={"foo": "bar"}))

    server = dap.DebugAdapterConnection()
    server.receive_data(client.data_to_send())
    with pytest.raises(ValueError, match="Expected seq 1 but received 2"):
        server.next_message()


def test_receive_partial_message() -> None:
    msg = dap.InitializeRequest(
        adapter_id="Ansibug DAP",
        client_id="My Client",
        supports_variable_type=True,
    )
    client = dap.DebugAdapterConnection()
    client.queue_msg(msg)

    server = dap.DebugAdapterConnection()
    server.receive_data(client.data_to_send(10))
    assert server.next_message() is None

    # Received the full header but still not enough data
    server.receive_data(client.data_to_send(20))
    assert server.next_message() is None

    server.receive_data(client.data_to_send())

    actual = server.next_message()
    assert isinstance(actual, dap.InitializeRequest)
    assert actual.seq == 1
    assert actual.adapter_id == "Ansibug DAP"
    assert actual.client_id == "My Client"
    assert actual.supports_variable_type

    assert server.next_message() is None


def test_receive_single_message() -> None:
    msg = dap.InitializeRequest(
        adapter_id="Ansibug DAP",
        client_id="My Client",
        supports_variable_type=True,
    )
    client = dap.DebugAdapterConnection()
    client.queue_msg(msg)

    server = dap.DebugAdapterConnection()
    server.receive_data(client.data_to_send())

    actual = server.next_message()
    assert isinstance(actual, dap.InitializeRequest)
    assert actual.seq == 1
    assert actual.adapter_id == "Ansibug DAP"
    assert actual.client_id == "My Client"
    assert actual.supports_variable_type

    assert server.next_message() is None


def test_receive_multiple_messages() -> None:
    class CustomObj:
        def __str__(self) -> str:
            return "custom"

    client = dap.DebugAdapterConnection()
    client.queue_msg(
        dap.InitializeRequest(
            adapter_id="Ansibug DAP",
            client_id="My Client",
            supports_variable_type=True,
        )
    )
    client.queue_msg(
        dap.LaunchRequest(
            arguments={"foo": "bar"},
            restart=CustomObj(),
        )
    )

    server = dap.DebugAdapterConnection()
    server.receive_data(client.data_to_send())

    actual = server.next_message()
    assert isinstance(actual, dap.InitializeRequest)
    assert actual.seq == 1
    assert actual.adapter_id == "Ansibug DAP"
    assert actual.client_id == "My Client"
    assert actual.supports_variable_type

    actual = server.next_message()
    assert isinstance(actual, dap.LaunchRequest)
    assert actual.seq == 2
    assert actual.arguments == {"foo": "bar"}
    assert actual.no_debug is False
    assert actual.restart == "custom"

    assert server.next_message() is None
