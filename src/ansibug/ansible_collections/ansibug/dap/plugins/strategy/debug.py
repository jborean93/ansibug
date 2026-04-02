# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
name: debug
short_description: Executes tasks with a Debug Adapter Protocol debugger
description:
- Acts like the linear strategy plugin but adds functionality for interacting
  with a Debug Adapter Protocol (DAP) debugger, like one used by
  Visual Studio Code.
author: Jordan Borean (@jborean93)
"""

# We conditionally import our strategy so we can capture any broken imports or
# other import time errors that would occur. We loose all the extra work of
# hiding warnings about custom strategy plugins but at least we can display the
# error in a safe way that doesn't cause ansible-playbook to fail with a stack
# trace.
try:
    from ..plugin_utils._debug_strategy import StrategyModule

except Exception as e:
    import traceback

    from ansible.plugins.strategy import StrategyBase
    from ansible.utils.display import Display

    IMP_ERR = "".join(traceback.format_exception(e.__class__, e, e.__traceback__))

    class StrategyModule(StrategyBase):

        def run(self, *args, **kwargs) -> int:
            Display().error(
                f"Failed to import the ansibug strategy plugin due to the following import errors:\n{IMP_ERR}"
            )
            return 1
