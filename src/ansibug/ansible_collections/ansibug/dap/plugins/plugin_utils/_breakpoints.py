# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from ansible.playbook.block import Block
from ansible.playbook.play import Play
from ansible.playbook.task import Task

from ansibug._debuggee import AnsibleDebugger


def _split_task_path(task_path: str) -> tuple[str, int]:
    split = task_path.rsplit(":", 1)
    return split[0], int(split[1])


def register_block_breakpoints(
    debugger: AnsibleDebugger,
    blocks: list[Block],
) -> None:
    """Registers the block breakpoint locations.

    Registers all the valid breakpoints that can be found in the provided
    blocks with the debugger object. This is used to validate breakpoint
    locations as they are found.

    Args:
        debugger: The AnsibleDebugger object to register the breakpoints on.
        blocks: The blocks to scan for breakpoints.
    """
    # Need to register these blocks as valid breakpoints and update the client bps
    for block in blocks:
        block_path_and_line = block.get_path()
        if block_path_and_line:
            # If the path is set this is an explicit block and should be
            # marked as an invalid breakpoint section.
            block_path, block_line = _split_task_path(block_path_and_line)
            debugger.register_path_breakpoint(block_path, block_line, 0)

        task_list: list[Task] = block.block[:]
        task_list.extend(block.rescue)
        task_list.extend(block.always)

        for task in task_list:
            if isinstance(task, Block):
                # import_tasks will wrap the tasks in a standalone block.
                register_block_breakpoints(debugger, [task])

            else:
                task_path, task_line = _split_task_path(task.get_path())
                debugger.register_path_breakpoint(task_path, task_line, 1)


def register_play_breakpoints(
    debugger: AnsibleDebugger,
    plays: list[Play],
) -> None:
    """Registers the play breakpoint locations.

    Registers all the valid breakpoints that can be found in the provided plays
    with the debugger object. This is used to validate breakpoint locations as
    they are found.

    Args:
        debugger: The AnsibleDebugger object to register the breakpoints on.
        plays: The plays to scan for breakpoints.
    """
    for play in plays:
        # This is essentially doing what play.compile() does but without the
        # flush stages.
        play_path, play_line = _split_task_path(play.get_path())
        debugger.register_path_breakpoint(play_path, play_line, 1)

        play_blocks = play.compile() + play.handlers
        for r in play.roles:
            play_blocks += r.get_handler_blocks(play)

        register_block_breakpoints(debugger, play_blocks)
