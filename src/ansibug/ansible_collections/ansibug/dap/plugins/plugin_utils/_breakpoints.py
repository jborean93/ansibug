# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from ansible.playbook.block import Block
from ansible.playbook.play import Play
from ansible.playbook.task import Task

HAS_FORMAT_MESSAGE = False
try:
    from ansible.module_utils._internal._messages import ErrorSummary
    from ansible.utils.display import _format_message

    HAS_FORMAT_MESSAGE = True
except ImportError:
    pass

from ansibug._debuggee import AnsibleDebugger


def _format_exception(result: dict) -> str:
    text = str(result.get("msg", result.get("stdout", "Unknown error")))

    if exc := result.get("exception"):
        # Data Tagging has special method to format the exception tuple
        if HAS_FORMAT_MESSAGE and isinstance(exc, ErrorSummary):
            return _format_message(exc, False)

        text += f"\n\n{exc}"

    return text


def _split_task_path(task_path: str) -> tuple[str, int]:
    split = task_path.rsplit(":", 1)
    return split[0], int(split[1])


def get_on_failed_details(
    result: dict[str, object],
) -> tuple[str, str]:
    """Get failed task details.

    Gets the message and details of a failed task.

    Args:
        result: The result of the failed task.

    Returns:
        tuple[str, str]: A tuple containing the message and details of the
        failed task.
    """
    msg = "Task failed"

    return msg, _format_exception(result)


def get_on_unreachable_details(
    result: dict[str, object],
) -> tuple[str, str]:
    """Get unreachable task details.

    Gets the message and details of an unreachable task.

    Args:
        result: The result of the unreachable task.

    Returns:
        tuple[str, str]: A tuple containing the message and details of the
        unreachable task.
    """
    msg = "Host unreachable"

    return msg, _format_exception(result)


def get_on_skipped_details(
    result: dict[str, object],
) -> tuple[str, str]:
    """Get skipped task details.

    Gets the message and details of a skipped task.

    Args:
        result: The result of the skipped task.

    Returns:
        tuple[str, str]: A tuple containing the message and details of the
        skipped task.
    """
    msg = "Task skipped"
    text = f"{msg}\n{result.get('skip_reason', 'Unknown reason')}"

    if (false_condition := result.get("false_condition", None)) is not None:
        text += f"\n\nFalse condition: {false_condition}"

    return msg, text


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
                # 2.19 changed how the play's flush_handlers and implicit
                # no-op tasks are setup. It no longer has the loader path and
                # play details so skip registering these if not set.
                raw_task_path = task.get_path()
                if not raw_task_path:
                    continue

                task_path, task_line = _split_task_path(raw_task_path)
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
