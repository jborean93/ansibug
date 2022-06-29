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

from ansible.executor.play_iterator import PlayIterator
from ansible.playbook.play_context import PlayContext
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategyModule
from ansible.utils.display import Display

display = Display()


class StrategyModule(LinearStrategyModule):
    def run(
        self,
        iterator: PlayIterator,
        play_context: PlayContext,
    ) -> int:
        return super().run(iterator, play_context)
