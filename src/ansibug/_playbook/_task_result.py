# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ansible.inventory.host import Host
from ansible.playbook.task import Task

try:
    # 2.21+ strategy results.
    from ansible._internal._task import HostTaskResult
except ImportError:
    HostTaskResult = None


@dataclasses.dataclass(frozen=True)
class AnsibugTaskResult:
    """The task result details used by the debugger.

    Normalizes the various task result shapes the strategy receives across
    Ansible versions.

    Args:
        host: The host the task ran on.
        task: The task that ran.
        result: The raw task result, the same value used for register and
            not the censored copy given to callbacks.
        failed: The task failed.
        unreachable: The host was unreachable.
        skipped: The task was skipped.
        ignore_errors: The task has ignore_errors set.
        ignore_unreachable: The task has ignore_unreachable set.
    """

    host: Host
    task: Task
    result: dict[str, t.Any] = dataclasses.field(default_factory=dict)
    failed: bool = False
    unreachable: bool = False
    skipped: bool = False
    ignore_errors: bool = False
    ignore_unreachable: bool = False

    @classmethod
    def from_task_result(cls, result: t.Any) -> AnsibugTaskResult:
        """Create from the result returned by _process_pending_results."""
        if HostTaskResult and isinstance(result, HostTaskResult):
            # 2.21+ HostTaskResult object.
            utr = result.utr
            return cls(
                host=result.host,
                task=result.task,
                result=utr.as_result_dict(),
                failed=utr.failed,
                unreachable=bool(utr.unreachable),
                skipped=bool(utr.skipped),
                ignore_errors=utr.ignore_errors,
                ignore_unreachable=utr.ignore_unreachable,
            )

        elif hasattr(result, "_return_data"):
            # 2.19/2.20 raw strategy result.
            return cls(
                host=result.host,
                task=result.task,
                result=result._return_data,
                failed=result.is_failed(),
                unreachable=result.is_unreachable(),
                skipped=result.is_skipped(),
                ignore_errors=bool(result.task_fields.get("ignore_errors", None)),
                ignore_unreachable=bool(result.task_fields.get("ignore_unreachable", None)),
            )

        else:
            # Before 2.19, the results come from the raw TaskResult object.
            return cls(
                host=result._host,
                task=result._task,
                result=result._result,
                failed=result.is_failed(),
                unreachable=result.is_unreachable(),
                skipped=result.is_skipped(),
                ignore_errors=bool(result._task_fields.get("ignore_errors", None)),
                ignore_unreachable=bool(result._task_fields.get("ignore_unreachable", None)),
            )

    @classmethod
    def from_meta_task(cls, host: Host, task: Task) -> AnsibugTaskResult:
        """Create for a meta task which has no result."""
        return cls(host=host, task=task)
