from __future__ import annotations

DOCUMENTATION = r"""
author: Jordan Borean
name: broken_connection
short_description: Test connection plugin to test broken connections.
description:
  - Test connection plugin used in the exception breakpoint tests.
options: {}
"""

from ansible.errors import AnsibleConnectionFailure
from ansible.plugins.connection import ConnectionBase


class Connection(ConnectionBase):
    transport = "ns.name.broken_connection"
    has_pipelining = True

    def _connect(self) -> Connection:
        raise AnsibleConnectionFailure("Connection is broken")

    def exec_command(self, cmd: str, in_data: bytes | None = None, sudoable: bool = True) -> tuple[int, bytes, bytes]:
        raise AnsibleConnectionFailure("Connection is broken")

    def put_file(self, in_path: str, out_path: str) -> None:
        raise AnsibleConnectionFailure("Connection is broken")

    def fetch_file(self, in_path: str, out_path: str) -> None:
        raise AnsibleConnectionFailure("Connection is broken")

    def close(self) -> None:
        self._connected = False
