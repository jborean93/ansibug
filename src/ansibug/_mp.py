# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import multiprocessing
import queue
import typing as t
from multiprocessing.managers import BaseManager, Server

multiprocessing.Manager


class DAPManager(BaseManager):
    """Multiprocessing DAP Manager.

    This class is used to proxy DAP messages between the DA server and the
    Ansible process. It exposes a convenience recv and send functions that
    used a proxied queue to exchange messages.
    """

    @property
    def _role(self) -> str:
        """Used internally to denote the manager role."""

    def _get_ansible_queue(self) -> queue.Queue[t.Any]:
        """Used internally to store the queue used in Ansible."""

    def _get_da_queue(self) -> queue.Queue[t.Any]:
        """Used internally to store the queue used in the DA."""

    def send(
        self,
        msg: t.Any,
    ) -> None:
        """Send a message to the peer.

        Sends the message to the peer on the other end of the manager.

        Args:
            msg: The message to send.
        """
        q = self._get_da_queue() if self._role == "client" else self._get_ansible_queue()
        q.put(msg)

    def recv(self) -> t.Any:
        """Receive a message from the peer.

        Receives a message from the peer on the other end of the manager.

        Returns:
            t.Any: The object sent by the peer.
        """
        q = self._get_ansible_queue() if self._role == "client" else self._get_da_queue()
        return q.get()

    def stop(self) -> None:
        """Stops the server proxy thread.

        Stops the thread that handles all the proxies data. Can only be called
        by the da role.
        """
        # This is overriden in the server_manager to actually stop the server.
        raise Exception("Cannot be stopped by a client.")


def server_manager(
    address: t.Tuple[str, int],
    authkey: t.Optional[bytes] = None,
) -> t.Tuple[DAPManager, Server]:
    """Create a server side manager.

    Creates a server side manager that is used to proxy objects between the DA
    server and Ansible process.

    Args:
        address: The address to bind to.
        authkey: The byte string used for initial authentication.

    Returns:
        Tuple[DAPManager, Server]: The server manager and server instance. The
        caller should call server.server_forever() in a separate thread to
        allow it to process incoming data.
    """
    da_queue: queue.Queue[t.Any] = queue.Queue()
    ansible_queue: queue.Queue[t.Any] = queue.Queue()

    m = t.cast(t.Type[DAPManager], type("ServerDAPManager", (DAPManager,), {"_role": "server"}))
    m.register("_get_da_queue", lambda: da_queue)
    m.register("_get_ansible_queue", lambda: ansible_queue)

    server = m(address=address, authkey=authkey).get_server()

    # Create a new instance with the actual address used
    manager = m(address=server.address, authkey=authkey)
    setattr(manager, "stop", lambda: server.stop_event.set())  # type: ignore[attr-defined]  # Defined at runtime

    return manager, server


def client_manager(
    address: t.Tuple[str, int],
    authkey: t.Optional[bytes] = None,
) -> DAPManager:
    """Create a client side manager.

    Creates a client side manager that is used to proxy objects between the DA
    server and Ansible process.

    Args:
        address:
        authkey: The byte string used for initial authentication.

    Returns:
        DAPManager: The client DAP manager that is connected to the addr
        specified.
    """
    m = t.cast(t.Type[DAPManager], type("ClientDAPManager", (DAPManager,), {"_role": "client"}))
    m.register("_get_da_queue")
    m.register("_get_ansible_queue")

    return m(address=address, authkey=authkey)
