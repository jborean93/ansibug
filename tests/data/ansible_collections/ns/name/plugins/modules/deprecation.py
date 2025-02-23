#!/usr/bin/python

from __future__ import annotations

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    module = AnsibleModule(argument_spec={}, supports_check_mode=True)
    result = {
        "changed": False,
    }

    module.deprecate("Test deprecation", version="2.99")
    module.exit_json(**result)


if __name__ == "__main__":
    main()
