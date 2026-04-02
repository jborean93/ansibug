# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import contextlib
import io
import json
import os
import pathlib
import queue
import signal
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
    # env |= {
    #     "ANSIBLE_LOG_PATH": "/tmp/ansibug-ansible.log",
    #     "ANSIBLE_DEBUG": "True",
    # }

    return env


class UnexpectedResponse(Exception):
    """Used when an unexpected DAP response is received."""

    pass


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
        self._dap_stdin = t.cast(io.BytesIO, self._dap_proc.stdin)
        self._dap_stderr: bytes | None = None

        self._dap_stdout_thread = threading.Thread(
            target=self._dap_stdout_recv,
            args=(self._dap_proc.stdout,),
            name="DAPClient-stdout-recv",
        )
        self._dap_stderr_thread = threading.Thread(
            target=self._dap_stderr_recv,
            args=(self._dap_proc.stderr,),
            name="DAPClient-stderr-recv",
        )
        self._incoming_msg: queue.Queue[dap.ProtocolMessage | None] = queue.Queue()

        self._ansible_proc: AnsibleProcess | None = None

    def __enter__(self) -> DAPClient:
        self._dap_stdout_thread.start()
        self._dap_stderr_thread.start()
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

        self._dap_stdout_thread.join()
        self._dap_stderr_thread.join()

        self._dap_proc.communicate(None)

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
            stderr = self._dap_stderr or b"Unknown error"
            raise Exception(f"DAP process has ended with {rc}: {stderr.decode()}")

        self._client.queue_msg(msg)
        self._dap_stdin.write(self._client.data_to_send())

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
            if self._ansible_proc and self._ansible_proc.stdout:
                stderr = self._dap_stderr or b"Unknown error"
                raise Exception(
                    f"Ansible process has ended with {self._ansible_proc._proc.returncode}: {self._ansible_proc.stdout.decode()}"
                )

            else:
                stderr = self._dap_stderr or b"Unknown error"
                raise Exception(f"DAP process has ended with {self._dap_proc.poll()}: {stderr.decode()}")

        elif isinstance(msg, dap.ErrorResponse) and expected_type != dap.ErrorResponse:
            raise UnexpectedResponse(f"Received error response for {msg.command.value}: {msg.message}")

        elif not isinstance(msg, expected_type):
            raise UnexpectedResponse(
                f"Received unexpected response type {type(msg)} but expected {expected_type}: {msg}"
            )

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
        proc = self._start_ansible_process(
            proc_args,
            cwd=playbook_dir,
            env=new_environment,
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

    @contextlib.contextmanager
    def launch2(
        self,
        playbook: str | pathlib.Path,
        playbook_dir: str | pathlib.Path | None = None,
        playbook_args: list[str] | None = None,
        launch_options: dict[str, t.Any] | None = None,
        do_not_launch: bool = False,
        expected_terminated: bool = False,
        check_request: collections.abc.Callable[[dap.RunInTerminalRequest], None] | None = None,
    ) -> t.Iterable[AnsibleProcess]:
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

        with self._start_ansible_process(
            resp.args,
            cwd=resp.cwd,
            env=new_environment,
        ) as proc:
            self.send(dap.RunInTerminalResponse(request_seq=resp.seq, process_id=proc._proc.pid))

            # Run these with a timeout to ensure the process actually started
            # and there were no syntax errors crashing it.
            if expected_terminated:
                self.wait_for_message(dap.TerminatedEvent)
            else:
                self.wait_for_message(dap.LaunchResponse)
                self.wait_for_message(dap.InitializedEvent)

            yield proc

    def _start_ansible_process(
        self,
        args: list[str],
        cwd: str,
        env: dict[str, str],
    ) -> AnsibleProcess:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Ensures we can send the SIGINT and SIGKILL to Ansible and not
            # impact us.
            start_new_session=True,
        )

        return AnsibleProcess(proc, self._incoming_msg)

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

    def _dap_stdout_recv(
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

    def _dap_stderr_recv(
        self,
        stderr: io.BytesIO,
    ) -> None:
        self._dap_stderr = stderr.read()
        a = ""


class AnsibleProcess:

    def __init__(
        self,
        proc: subprocess.Popen,
        msg_queue: queue.Queue[None],
    ) -> None:
        self._proc = proc
        self._msg_queue = msg_queue
        self._listener_thread = threading.Thread(
            target=self._listen_stdout,
            name="AnsibleProcess-stdout-listener",
        )
        self._listener_thread.start()

        self.stdout = b""

    @property
    def id(self) -> int:
        return self._proc.pid

    def __enter__(self) -> AnsibleProcess:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None = None,
        exception_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
        **kwargs: t.Any,
    ) -> None:
        if exception_type and issubclass(exception_type, UnexpectedResponse):
            # If we got an UnexpectedResponse exception we try and stop the
            # running Ansible Process with CTRL+C and hopefully get its output.
            # If it is still running we have a deadlock with Ansible so SIGKILL
            # it after 5 seconds and get whatever output we have.
            try:
                os.killpg(self._proc.pid, signal.SIGINT)
            except OSError:
                pass

            self._listener_thread.join(timeout=5.0)
            if self._listener_thread.is_alive():
                os.killpg(self._proc.pid, signal.SIGKILL)
                self._listener_thread.join()

            play_out = f"Ansible process failed with the following output\n{self.stdout.decode()}"
            raise exception_value from Exception(play_out)

        return

    def check_return_code(
        self,
        expected: int = 0,
    ) -> None:
        # self._listener_thread.join()
        actual_rc = self._proc.returncode
        if actual_rc != expected:
            raise Exception(f"Playbook failed {actual_rc} but expected {expected}\{self.stdout.decode()}")

    def _listen_stdout(self) -> None:
        self.stdout, _ = self._proc.communicate()

        # If the rc was non zero we signal that no more messages will come
        if self._proc.returncode:
            self._msg_queue.put(None)
