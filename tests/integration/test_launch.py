# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient, DAPErrorResponse

import ansibug.dap as dap


def test_launch_no_playbook(
    dap_client: DAPClient,
) -> None:
    with pytest.raises(DAPErrorResponse, match="Expected playbook to be specified for launch"):
        dap_client.send(dap.LaunchRequest(arguments={}), dap.LaunchResponse)


def test_launch_invalid_console(
    dap_client: DAPClient,
) -> None:
    launch_args = {"playbook": "main.yml", "console": "invalid"}

    expected = "Unknown console value 'invalid' - expected integratedTerminal or externalTerminal"
    with pytest.raises(DAPErrorResponse, match=expected):
        dap_client.send(dap.LaunchRequest(arguments=launch_args), dap.LaunchResponse)


def test_launch_with_logging(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> None:
    dap_log_file = tmp_path / f"ansibug-{request.node.name}-dap.log"
    debuggee_log_file = tmp_path / f"ansibug-{request.node.name}-debuggee.log"

    with DAPClient(request.node.name, log_dir=tmp_path) as client:
        client.initialize()

        playbook = tmp_path / "main.yml"
        playbook.write_text(
            r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
        )

        proc = client.launch(playbook, playbook_dir=tmp_path)

        client.configuration_done()
        client.wait_for_end(proc)

        assert dap_log_file.exists()
        assert debuggee_log_file.exists()


def test_launch_with_timeout(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    expected = r"Timed out waiting for socket.accept\(\)"
    with pytest.raises(DAPErrorResponse, match=expected):
        dap_client.launch(
            ping_playbook,
            playbook_dir=tmp_path,
            launch_options={
                "connectTimeout": 0.1,
            },
            do_not_launch=True,
        )


def test_launch_with_invalid_playbook(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
gather_facts: false
"""
    )

    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        expected_terminated=True,
    )

    proc.communicate()
    assert proc.returncode != 0


def test_launch_process_ends_before_connect(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks: []
"""
    )

    # An invalid arg makes ansible-playbook exit before it connects back.
    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        playbook_args=["--invalid-arg"],
        expected_terminated=True,
    )
    proc.communicate()
    assert proc.returncode != 0

    dap_client.send(dap.DisconnectRequest(), dap.DisconnectResponse)

    # The DA server should exit cleanly without a further ErrorResponse.
    assert dap_client._incoming_msg.get(timeout=10) is None
    assert dap_client._dap_proc.wait() == 0


def test_launch_failure_after_connect(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: '{{ undefined_var }}'
  gather_facts: false
  tasks: []
"""
    )

    # Fails after the debuggee connected so v2_playbook_on_stats never runs.
    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    proc.communicate(timeout=30)
    assert proc.returncode != 0


def test_launch_with_disconnect(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 8)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.DisconnectRequest(terminate_debuggee=False), dap.DisconnectResponse)

    play_out = proc.wait_rc()

    assert "ok=3" in play_out[0]


def test_launch_with_terminate(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 8)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminateResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.wait_rc(2)
    stdout = play_out[0]
    play_out[1]

    assert "Debugger has requested the process to terminate" in stdout
    assert "ok=1" in stdout


def test_launch_with_terminate_multiple_plays(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- name: play 1
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:

- name: play 2
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 4
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 9)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminateResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.wait_rc(2)
    stdout = play_out[0]
    play_out[1]

    assert "PLAY [play 1]" in stdout
    assert "Debugger has requested the process to terminate" in stdout
    assert "PLAY [play 2]" not in stdout
    assert "ok=1" in stdout


def test_launch_with_tempdir(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> None:
    with DAPClient(request.node.name, temp_dir=tmp_path) as client:
        client.initialize()

        playbook = tmp_path / "main.yml"
        playbook.write_text(
            r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
        )

        def check_launch(request: dap.RunInTerminalRequest) -> None:
            launch_found = False
            for file in tmp_path.iterdir():
                if file.name.startswith("ansibug-launch-"):
                    assert request.args[0] == "/bin/sh"
                    assert str(file.absolute()) == request.args[1]
                    launch_found = True
                    break

            assert launch_found

        proc = client.launch(playbook, playbook_dir=tmp_path, check_request=check_launch)

        client.configuration_done()
        client.wait_for_end(proc)
