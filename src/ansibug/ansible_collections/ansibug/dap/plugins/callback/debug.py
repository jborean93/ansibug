# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
name: debug
type: aggregate
short_description: Ansible Debug Adapter Protocol Callback Plugin
description:
- The callback plugin used to handle the DAP socket connections.
author: Jordan Borean (@jborean93)
options:
  debug_host:
    description:
    - The hostname to bind the debug adapter socket to.
    type: str
    default: 127.0.0.1
    env:
    - name: ANSIBUG_HOSTNAME
  debug_port:
    description:
    - The port to bind the debug adapter socket to.
    type: int
    ini:
    - section: ansibug
      key: port
    env:
    - name: ANSIBUG_PORT
    vars:
    - name: ansible_ansibug_port
"""

import typing as t

from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "debug"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        super().__init__(*args, **kwargs)

    def v2_playbook_on_start(
        self,
        playbook: Playbook,
    ) -> None:
        host = self.get_option("debug_host")
        port = self.get_option("debug_port")
        addr_info = f"{host}:{port}"

        print(f"Starting ansibug.dap.debug callback for {addr_info}")

    def v2_playbook_on_stats(
        self,
        stats: AggregateStats,
    ) -> None:
        print(f"Ending ansbug.dap.debug callback")
