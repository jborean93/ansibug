# Copyright (c) 2025 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from ansibug.ansible_collections.ansibug.dap.plugins.plugin_utils._breakpoints import (
    get_on_failed_details,
    get_on_skipped_details,
    get_on_unreachable_details,
)


def test_get_failed_details_all_fields() -> None:
    expected = "Task failed\nfailed\n\nfoo"
    actual_msg, actual_details = get_on_failed_details(
        {
            "msg": "failed",
            "stdout": "value",
            "exception": "foo",
        }
    )

    assert "Task failed" == actual_msg
    assert expected == actual_details


def test_get_failed_details_no_msg() -> None:
    expected = "Task failed\nfailed\n\nfoo"
    actual_msg, actual_details = get_on_failed_details(
        {
            "stdout": "failed",
            "exception": "foo",
        }
    )

    assert "Task failed" == actual_msg
    assert expected == actual_details


def test_get_failed_details_no_msg_or_stdout() -> None:
    expected = "Task failed\nUnknown error\n\nfoo"
    actual_msg, actual_details = get_on_failed_details(
        {
            "exception": "foo",
        }
    )

    assert "Task failed" == actual_msg
    assert expected == actual_details


def test_get_failed_details_no_exception() -> None:
    expected = "Task failed\nfailed"
    actual_msg, actual_details = get_on_failed_details(
        {
            "msg": "failed",
        }
    )

    assert "Task failed" == actual_msg
    assert expected == actual_details


def test_get_unreachable_details_all_fields() -> None:
    expected = "Host unreachable\nfailed\n\nfoo"
    actual_msg, actual_details = get_on_unreachable_details(
        {
            "msg": "failed",
            "stdout": "value",
            "exception": "foo",
        }
    )

    assert "Host unreachable" == actual_msg
    assert expected == actual_details


def test_get_unreachable_details_no_msg() -> None:
    expected = "Host unreachable\nfailed\n\nfoo"
    actual_msg, actual_details = get_on_unreachable_details(
        {
            "stdout": "failed",
            "exception": "foo",
        }
    )

    assert "Host unreachable" == actual_msg
    assert expected == actual_details


def test_get_unreachable_details_no_msg_or_stdout() -> None:
    expected = "Host unreachable\nUnknown error\n\nfoo"
    actual_msg, actual_details = get_on_unreachable_details(
        {
            "exception": "foo",
        }
    )

    assert "Host unreachable" == actual_msg
    assert expected == actual_details


def test_get_unreachable_details_no_exception() -> None:
    expected = "Host unreachable\nfailed"
    actual_msg, actual_details = get_on_unreachable_details(
        {
            "msg": "failed",
        }
    )

    assert "Host unreachable" == actual_msg
    assert expected == actual_details


def test_get_skipped_details_all_fields() -> None:
    expected = "Task skipped\nreason\n\nFalse condition: foo"
    actual_msg, actual_details = get_on_skipped_details(
        {
            "skip_reason": "reason",
            "false_condition": "foo",
        }
    )

    assert "Task skipped" == actual_msg
    assert expected == actual_details


def test_get_skipped_details_no_reason() -> None:
    expected = "Task skipped\nUnknown reason\n\nFalse condition: foo"
    actual_msg, actual_details = get_on_skipped_details(
        {
            "false_condition": "foo",
        }
    )

    assert "Task skipped" == actual_msg
    assert expected == actual_details


def test_get_skipped_details_no_false_condition() -> None:
    expected = "Task skipped\nreason"
    actual_msg, actual_details = get_on_skipped_details(
        {
            "skip_reason": "reason",
        }
    )

    assert "Task skipped" == actual_msg
    assert expected == actual_details
