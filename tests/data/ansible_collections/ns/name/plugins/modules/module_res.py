#!/usr/bin/python

from __future__ import annotations

import datetime

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    module = AnsibleModule(
        argument_spec={},
        supports_check_mode=True,
    )

    module.exit_json(
        str="str value",
        int=9,
        float=1.2,
    )


if __name__ == "__main__":
    main()
