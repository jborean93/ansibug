# (c) 2012-2014, Ansible, Inc
# (c) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
name: ns.name.custom
type: notification
short_description: Custom callback for ns.name
description:
- Description for ns.name.custom
options:
  result_file:
    description:
    - File path to create the final result file.
    type: path
    required: true
    env:
    - name: ANSIBUG_TEST_RESULT_FILE
"""

import typing as t

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "ns.name.custom"
    CALLBACK_NEEDS_ENABLED = True

    def v2_playbook_on_stats(self, stats: t.Any) -> None:
        result_file = self.get_option("result_file")
        with open(result_file, mode="w") as fd:
            fd.write("done")
