# Copyright: (c) 2023, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r"""
name: inv
author: Jordan Borean (@jborean93)
short_description: Test inv plugin.
description:
- Inventory plugin for testing refresh_host.
options:
  hosts_file:
    description:
    - The file containing the list of hosts to generate as localhost.
    type: str
    required: true
"""

EXAMPLES = r"""
"""

import sys

from ansible.inventory.data import InventoryData
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.inventory import BaseInventoryPlugin, Constructable


class InventoryModule(BaseInventoryPlugin, Constructable):
    NAME = "ns.name.inv"

    def verify_file(self, path: str) -> bool:
        if super().verify_file(path):
            return path.endswith("name.inv.yml")

        return False

    def parse(
        self,
        inventory: InventoryData,
        loader: DataLoader,
        path: str,
        cache: bool,
    ) -> None:
        super().parse(inventory, loader, path, cache)

        self._read_config_data(path)

        hosts_file = self.get_option("hosts_file")
        with open(hosts_file, mode="r") as fd:
            for host in fd:
                hostname = host.rstrip()
                inventory.add_host(hostname)
                inventory.set_variable(hostname, "ansible_connection", "local")
                inventory.set_variable(hostname, "ansible_python_interpreter", sys.executable)
