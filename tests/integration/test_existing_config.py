# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil
import uuid

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

    dap_client.set_breakpoints(playbook, 5)

    tid = dap_client.configuration_done()
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.continue_to_end(proc, tid)

    assert result_file.exists()


def test_playbook_default_collections_path(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    # This is the only test that should touch the user's real collections
    # path as it checks the default path still works under ansibug, any other
    # test must use a collections dir in tmp_path. The namespace is unique so
    # it cannot clash with or remove an installed collection or another run.
    namespace = f"ansibug_test_{uuid.uuid4().hex}"

    playbook = tmp_path / "main.yml"
    playbook.write_text(
        rf"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    {namespace}.temp.ping:
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
    temp_collection_root = pathlib.Path("~/.ansible/collections/ansible_collections").expanduser() / namespace
    temp_collection_module_dir = temp_collection_root / "temp" / "plugins" / "modules"
    temp_collection_module_dir.mkdir(parents=True)
    try:
        shutil.copy(ping_src, temp_collection_module_dir / "ping.py")

        proc = dap_client.launch(
            playbook,
            playbook_dir=tmp_path,
        )

        dap_client.set_breakpoints(playbook, 5)

        tid = dap_client.configuration_done()
        dap_client.wait_for_message(dap.StoppedEvent)
        dap_client.continue_to_end(proc, tid)

    finally:
        shutil.rmtree(temp_collection_root)


def test_ansible_config_verbosity(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
verbosity = 3
"""
    )

    proc = dap_client.launch(
        ping_playbook,
        playbook_dir=tmp_path,
        launch_options={
            "env": {
                "ANSIBLE_CONFIG": str(ansible_cfg.absolute()),
            }
        },
    )

    dap_client.set_breakpoints(ping_playbook, 5)

    tid = dap_client.configuration_done()
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.continue_to_end(proc, tid)


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

        dap_client.set_breakpoints(playbook, 5)

        tid = dap_client.configuration_done()
        dap_client.wait_for_message(dap.StoppedEvent)
        _, stderr = dap_client.continue_to_end(proc, tid)

    finally:
        shutil.rmtree(temp_collection_root)

    assert "Use of strategy plugins not included in ansible.builtin are deprecated" not in stderr, (
        f"Strategy plugin msg was found in {stderr}"
    )

    if deprecation_warnings:
        assert "Test deprecation" in stderr, f"Failed to find deprecation msg in {stderr}"
    else:
        assert "Test deprecation" not in stderr, f"Found deprecation msg in {stderr}"
