# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_launch_no_playbook(
    dap_client: DAPClient,
) -> None:
    with pytest.raises(Exception, match="Expected playbook to be specified for launch"):
        dap_client.send(dap.LaunchRequest(arguments={}), dap.LaunchResponse)


def test_launch_invalid_console(
    dap_client: DAPClient,
) -> None:
    launch_args = {"playbook": "main.yml", "console": "invalid"}

    expected = "Unknown console value 'invalid' - expected integratedTerminal or externalTerminal"
    with pytest.raises(Exception, match=expected):
        dap_client.send(dap.LaunchRequest(arguments=launch_args), dap.LaunchResponse)
