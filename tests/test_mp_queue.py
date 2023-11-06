# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import socket

import pytest

from ansibug import _mp_queue as mpq


def test_connect_failure_unknown_target() -> None:
    with mpq.ClientMPQueue("tcp://unknown:12345", mpq.MPProtocol) as client:
        # The error message differs depending on the host, just check there
        # was an error.
        with pytest.raises(OSError):
            client.start()


def test_connect_failure_refused() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        addr = server.getsockname()

        with mpq.ClientMPQueue(f"tcp://{addr[0]}:{addr[1]}", mpq.MPProtocol) as client:
            with pytest.raises(OSError, match="Connection refused"):
                client.start()
