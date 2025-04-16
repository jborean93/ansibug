# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_playbook_existing_config(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ns.name.ping:
"""
    )

    collections_path = pathlib.Path(__file__).parent.parent / "data"
    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
callbacks_enabled = ns.name.custom
collections_path = {collections_path.absolute()!s}
"""
    )

    result_file = tmp_path / "callback_result.txt"
    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        launch_options={
            "env": {
                "ANSIBLE_CONFIG": str(ansible_cfg.absolute()),
                "ANSIBUG_TEST_RESULT_FILE": str(result_file.absolute()),
            }
        },
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

    assert result_file.exists()


def test_playbook_default_collections_path(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ansibug.temp.ping:
"""
    )

    ping_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "modules"
        / "ping.py"
    )
    temp_collection_root = pathlib.Path("~/.ansible/collections/ansible_collections/ansibug").expanduser()
    temp_collection_module_dir = temp_collection_root / "temp" / "plugins" / "modules"
    temp_collection_module_dir.mkdir(parents=True)
    try:
        shutil.copy(ping_src, temp_collection_module_dir / "ping.py")

        proc = dap_client.launch(
            playbook,
            playbook_dir=tmp_path,
        )

        dap_client.send(
            dap.SetBreakpointsRequest(
                source=dap.Source(
                    name="main.yml",
                    path=str(playbook.absolute()),
                ),
                lines=[5],
                breakpoints=[dap.SourceBreakpoint(line=5)],
                source_modified=False,
            ),
            dap.SetBreakpointsResponse,
        )

        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

        thread_event = dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.StoppedEvent)
        dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
        dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()

    finally:
        shutil.rmtree(temp_collection_root)

    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_ansible_config_verbosity(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
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

    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
verbosity = 3
"""
    )

    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        launch_options={
            "env": {
                "ANSIBLE_CONFIG": str(ansible_cfg.absolute()),
            }
        },
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


@pytest.mark.parametrize("deprecation_warnings", [True, False])
def test_allow_deprecation_message(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    deprecation_warnings: bool,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: deprecation test
    ansibug.temp.deprecation:
"""
    )

    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
deprecation_warnings = {deprecation_warnings}
"""
    )

    deprecation_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "modules"
        / "deprecation.py"
    )
    temp_collection_root = tmp_path / "collections" / "ansible_collections" / "ansibug"
    temp_collection_module_dir = temp_collection_root / "temp" / "plugins" / "modules"
    temp_collection_module_dir.mkdir(parents=True)
    try:
        shutil.copy(deprecation_src, temp_collection_module_dir / "deprecation.py")

        proc = dap_client.launch(
            playbook,
            playbook_dir=tmp_path,
        )

        dap_client.send(
            dap.SetBreakpointsRequest(
                source=dap.Source(
                    name="main.yml",
                    path=str(playbook.absolute()),
                ),
                lines=[5],
                breakpoints=[dap.SourceBreakpoint(line=5)],
                source_modified=False,
            ),
            dap.SetBreakpointsResponse,
        )

        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

        thread_event = dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.StoppedEvent)
        dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
        dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()

    finally:
        shutil.rmtree(temp_collection_root)

    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

    stderr = play_out[1].decode()

    assert (
        "Use of strategy plugins not included in ansible.builtin are deprecated" not in stderr
    ), f"Strategy plugin msg was found in {stderr}"

    if deprecation_warnings:
        assert "Test deprecation" in stderr, f"Failed to find deprecation msg in {stderr}"
    else:
        assert "Test deprecation" not in stderr, f"Found deprecation msg in {stderr}"
