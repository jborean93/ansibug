# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Tests for the test harness itself, a hung Ansible process must not hang the test."""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import time

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_hung_ansible_times_out(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: hang
    command: sleep 600
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.configuration_done()

    with pytest.raises(TimeoutError, match="Timed out waiting for TerminatedEvent"):
        dap_client.wait_for_message(dap.TerminatedEvent, timeout=2)

    with pytest.raises(subprocess.TimeoutExpired):
        proc.communicate(timeout=2)

    start = time.monotonic()
    proc.stop()
    assert time.monotonic() - start < 15
    assert proc.returncode is not None
    assert "TASK [hang]" in proc.format_output()


def test_killed_ansible_fails_fast(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: hang
    command: sleep 600
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.configuration_done()

    os.killpg(proc.pid, signal.SIGKILL)

    # The DA server may relay a TerminatedEvent first; either way the wait must
    # fail well before the default timeout instead of hanging.
    start = time.monotonic()
    with pytest.raises(Exception):
        while True:
            dap_client.wait_for_message(dap.StoppedEvent)
    assert time.monotonic() - start < 15
