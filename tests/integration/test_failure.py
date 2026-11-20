# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import pathlib
import socket
import sys
import tempfile

import pytest
from dap_client import AnsibleProcess, DAPClient, get_test_env

import ansibug.dap as dap


@pytest.fixture
def sock_dir() -> collections.abc.Iterator[pathlib.Path]:
    # tmp_path on macOS exceeds the 104 byte AF_UNIX path limit.
    with tempfile.TemporaryDirectory() as d:
        yield pathlib.Path(d)


def test_unknown_message(
    dap_client: DAPClient,
) -> None:
    # Sending a debuggee intended message before its connected is rejected
    # without ending the adapter.
    req = dap.ConfigurationDoneRequest()
    dap_client.send(req)
    resp = dap_client.wait_for_message(dap.ErrorResponse)

    assert resp.request_seq == req.seq
    assert resp.command == dap.Command.CONFIGURATION_DONE
    assert resp.message == "The configurationDone request needs a launched or attached playbook"

    # The adapter is still running.
    dap_client.send(dap.ThreadsRequest())
    dap_client.wait_for_message(dap.ErrorResponse)


def test_unknown_message_on_debuggee(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    proc = dap_client.launch(ping_playbook, playbook_dir=tmp_path)

    # After the debuggee is connected any requests are forwarded to it from the
    # DA server. This tests out how it reacts with an unknown request.
    err = dap_client.send(dap.LaunchRequest(arguments={}), dap.ErrorResponse)
    assert isinstance(err, dap.ErrorResponse)
    assert err.message
    assert "NotImplementedError: Debuggee does not support the LaunchRequest message" in err.message

    # We should be able to continue on as normal though
    dap_client.configuration_done()
    dap_client.wait_for_end(proc)


def test_connect_failure(
    tmp_path: pathlib.Path,
    sock_dir: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    proc = AnsibleProcess(
        [
            sys.executable,
            "-m",
            "ansibug",
            "connect",
            "--addr",
            f"uds://{sock_dir / 'missing.sock'}",
            str(ping_playbook),
        ],
        cwd=tmp_path,
        env=get_test_env(),
    )
    try:
        stdout, stderr = proc.communicate()
    finally:
        proc.stop()

    # The connection is made before the playbook runs.
    assert proc.returncode == 1, proc.format_output()
    assert b"ansibug: failed to start the debugger: FileNotFoundError:" in stderr
    assert b"PLAY" not in stdout


def test_connect_timeout(
    tmp_path: pathlib.Path,
    sock_dir: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    # The listener never accepts so the connect handshake never completes.
    sock_path = sock_dir / "unresponsive.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(sock_path))
        listener.listen()

        proc = AnsibleProcess(
            [
                sys.executable,
                "-m",
                "ansibug",
                "connect",
                "--addr",
                f"uds://{sock_path}",
                "--connect-timeout",
                "0.5",
                str(ping_playbook),
            ],
            cwd=tmp_path,
            env=get_test_env(),
        )
        try:
            stdout, stderr = proc.communicate()
        finally:
            proc.stop()

    assert proc.returncode == 1, proc.format_output()
    assert b"ansibug: failed to start the debugger: TimeoutError:" in stderr
    assert b"PLAY" not in stdout


def test_debugger_setup_failure(
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    # Errors setting up the debugger fail before the playbook runs.
    proc = AnsibleProcess(
        [
            sys.executable,
            "-m",
            "ansibug",
            "listen",
            "--no-wait",
            "--log-file",
            str(tmp_path / "missing" / "debuggee.log"),
            str(ping_playbook),
        ],
        cwd=tmp_path,
        env=get_test_env(),
    )
    try:
        stdout, stderr = proc.communicate()
    finally:
        proc.stop()

    assert proc.returncode == 1, proc.format_output()
    assert b"ansibug: failed to start the debugger: FileNotFoundError:" in stderr
    assert b"Traceback" not in stderr
    assert b"PLAY" not in stdout
