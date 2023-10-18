# -*- coding: utf-8 -*-

# (c) 2012, Michael DeHaan <michael.dehaan@gmail.com>
# (c) 2016, Toshio Kuratomi <tkuratomi@ansible.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
---
module: ns.name.ping
short_description: Ping description
description:
- Ping description
options:
  data:
    description:
    - Data to return for the RV(ping) return value.
    - If this parameter is set to V(crash), the module will cause an exception.
    type: str
    default: pong
extends_documentation_fragment:
- ansible.builtin.action_common_attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: none
  platform:
    platforms: posix
author:
- Ansible Core Team
"""

RETURN = """
ping:
  description: Value provided with the O(data) parameter.
  returned: success
  type: str
  sample: pong
"""

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    module = AnsibleModule(
        argument_spec=dict(
            data=dict(type="str", default="pong"),
        ),
        supports_check_mode=True,
    )

    if module.params["data"] == "crash":
        raise Exception("boom")

    result = dict(
        ping=module.params["data"],
    )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
