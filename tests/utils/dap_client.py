# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import io
import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time
import types
import typing as t

import ansibug.dap as dap
from ansibug._debuggee import get_pid_info_path

ResponseMessage = t.TypeVar("ResponseMessage", bound=dap.ProtocolMessage)


def get_test_env() -> dict[str, str]:
    env = os.environ | {"PYDEVD_DISABLE_FILE_VALIDATION": "1"}

    # We don't want this var from the outside to interfer with our test
    env.pop("ANSIBLE_CALLBACKS_ENABLED", None)
    env.pop("ANSIBLE_COLLECTIONS_PATH", None)
    env.pop("ANSIBLE_COLLECTIONS_PATHS", None)

    return env


class DAPClient:
    def __init__(
        self,
        test_name: str,
        log_dir: pathlib.Path | None = None,
        temp_dir: pathlib.Path | None = None,
    ) -> None:
        self._client = dap.DebugAdapterConnection()
        self._log_dir = log_dir
        self._test_name = test_name

        proc_env = get_test_env()
        dap_args = [
            sys.executable,
            "-m",
            "ansibug",
            "dap",
        ]
        if log_dir:
            dap_args.extend(
                [
                    "--log-file",
                    str((log_dir / f"ansibug-{test_name}-dap.log").absolute()),
                    "--log-level",
                    "debug",
                ]
            )
        if temp_dir:
            dap_args.extend(
                [
                    "--temp-dir",
                    str(temp_dir.absolute()),
                ]
            )

        self._dap_proc = subprocess.Popen(
            dap_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=proc_env,
        )
        self._stdin = t.cast(io.BytesIO, self._dap_proc.stdin)
        self._stderr: bytes | None = None

        self._stdout_thread = threading.Thread(
            target=self._stdout_recv,
            args=(self._dap_proc.stdout,),
            name="DAPClient-stdout-recv",
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_recv,
            args=(self._dap_proc.stderr,),
            name="DAPClient-stderr-recv",
        )
        self._incoming_msg: queue.Queue[dap.ProtocolMessage | None] = queue.Queue()

    def __enter__(self) -> DAPClient:
        self._stdout_thread.start()
        self._stderr_thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None = None,
        exception_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
        **kwargs: t.Any,
    ) -> None:
        if self._dap_proc.poll() is None:
            self.send(dap.DisconnectRequest())
            self._dap_proc.wait()

        self._dap_proc.communicate(None)

        self._stdout_thread.join()
        self._stderr_thread.join()

    @t.overload
    def send(self, msg: dap.ProtocolMessage) -> None: ...

    @t.overload
    def send(self, msg: dap.ProtocolMessage, return_type: type[ResponseMessage]) -> ResponseMessage: ...

    def send(
        self,
        msg: dap.ProtocolMessage,
        return_type: type[ResponseMessage] | None = None,
    ) -> ResponseMessage | None:
        if (rc := self._dap_proc.poll()) is not None:
            stderr = self._stderr or b"Unknown error"
            raise Exception(f"DAP process has ended with {rc}: {stderr.decode()}")

        self._client.queue_msg(msg)
        self._stdin.write(self._client.data_to_send())

        if not return_type:
            return None

        resp = self.wait_for_message(return_type)
        if isinstance(resp, dap.Response):
            assert msg.seq == resp.request_seq

        return resp

    def wait_for_message(
        self,
        expected_type: type[ResponseMessage],
    ) -> ResponseMessage:
        msg = self._incoming_msg.get(block=True)

        if not msg:
            stderr = self._stderr or b"Unknown error"
            raise Exception(f"DAP process has ended with {self._dap_proc.poll()}: {stderr.decode()}")

        elif isinstance(msg, dap.ErrorResponse) and expected_type != dap.ErrorResponse:
            raise Exception(f"Received error response for {msg.command.value}: {msg.message}")

        elif not isinstance(msg, expected_type):
            raise Exception(f"Received unexpected response type {type(msg)} but expected {expected_type}: {msg}")

        return msg

    def attach(
        self,
        playbook: str | pathlib.Path,
        playbook_dir: str | pathlib.Path | None = None,
        playbook_args: list[str] | None = None,
        ansibug_args: list[str] | None = None,
        attach_options: dict[str, t.Any] | None = None,
        attach_by_address: bool = False,
    ) -> subprocess.Popen:
        proc_args = [sys.executable, "-m", "ansibug", "listen"]
        if ansibug_args:
            proc_args += ansibug_args

        if self._log_dir and "--log-file" not in proc_args:
            proc_args.extend(
                [
                    "--log-file",
                    str((self._log_dir / f"ansibug-{self._test_name}-debuggee.log").absolute()),
                    "--log-level",
                    "debug",
                ]
            )

        proc_args.append(str(playbook))
        if playbook_args:
            proc_args += playbook_args

        new_environment = get_test_env()
        proc = subprocess.Popen(
            proc_args,
            cwd=playbook_dir,
            env=new_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        pid_path = get_pid_info_path(proc.pid)
        for _ in range(20):
            if pid_path.exists():
                break
            elif (rc := proc.poll()) is not None:
                stdout, stderr = proc.communicate()
                raise Exception(
                    f"Error when launching new ansible-playbook process\nRC: {rc}\nSTDOUT\n{stdout.decode()}\nSTDERR\n{stderr.decode()}"
                )

            time.sleep(1)
        else:
            proc.kill()
            raise Exception("timed out waiting for proc pid")

        if attach_by_address:
            proc_conn_data = json.loads(pid_path.read_text())
            proc_info = {"address": proc_conn_data["address"]}
        else:
            proc_info = {"processId": proc.pid}

        attach_arguments = (attach_options or {}) | proc_info
        if "connectTimeout" not in attach_arguments:
            # macOS in CI is quite slow, bump the timeout to 20
            attach_arguments["connectTimeout"] = 20.0

        self.send(dap.AttachRequest(arguments=attach_arguments), dap.AttachResponse)
        self.wait_for_message(dap.InitializedEvent)

        return proc

    def launch(
        self,
        playbook: str | pathlib.Path,
        playbook_dir: str | pathlib.Path | None = None,
        playbook_args: list[str] | None = None,
        launch_options: dict[str, t.Any] | None = None,
        do_not_launch: bool = False,
        expected_terminated: bool = False,
        check_request: collections.abc.Callable[[dap.RunInTerminalRequest], None] | None = None,
    ) -> subprocess.Popen:
        launch_args: dict[str, t.Any] = (launch_options or {}) | {"playbook": str(playbook)}
        if playbook_args:
            launch_args["args"] = playbook_args
        if playbook_dir:
            launch_args["cwd"] = str(playbook_dir)

        if self._log_dir and "logFile" not in launch_args:
            launch_args["logFile"] = str((self._log_dir / f"ansibug-{self._test_name}-debuggee.log").absolute())
            launch_args["logLevel"] = "debug"

        if "connectTimeout" not in launch_args:
            # macOS in CI is quite slow, bump the timeout to 20
            launch_args["connectTimeout"] = 20.0

        self.send(dap.LaunchRequest(arguments=launch_args))
        resp = self.wait_for_message(dap.RunInTerminalRequest)

        if check_request:
            check_request(resp)

        new_environment = get_test_env()
        if resp.env:
            new_environment = new_environment | {k: v or "" for k, v in resp.env.items()}

        if do_not_launch:
            # This is for a specific test that makes sure the timeout is honoured
            self.send(dap.RunInTerminalResponse(request_seq=resp.seq, process_id=1))
            self.wait_for_message(dap.LaunchResponse)
            raise Exception("This should not happen")

        else:
            proc = subprocess.Popen(
                resp.args,
                cwd=resp.cwd or None,
                env=new_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.send(dap.RunInTerminalResponse(request_seq=resp.seq, process_id=proc.pid))

            if expected_terminated:
                self.wait_for_message(dap.TerminatedEvent)
                return proc

            else:
                self.wait_for_message(dap.LaunchResponse)

        self.wait_for_message(dap.InitializedEvent)

        return proc

    def _stdout_recv(
        self,
        stdout: io.BytesIO,
    ) -> None:
        while True:
            data = stdout.read(4096)
            if not data:
                break

            self._client.receive_data(data)

            while msg := self._client.next_message():
                self._incoming_msg.put(msg)

        self._dap_proc.wait()
        self._incoming_msg.put(None)

    def _stderr_recv(
        self,
        stderr: io.BytesIO,
    ) -> None:
        self._stderr = stderr.read()
