#!/usr/bin/python

from __future__ import annotations

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "data": {"type": "str", "default": "pong"},
        },
        supports_check_mode=True,
    )

    if module.params["data"] == "crash":
        raise Exception("boom")

    result = {
        "ping": module.params["data"],
    }

    module.exit_json(**result)


if __name__ == "__main__":
    main()
