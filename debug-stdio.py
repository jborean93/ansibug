import json
import logging
import pathlib
import re
import sys
import typing as t

import debugpy

import ansibug._dap.messages as dap

logging.basicConfig(
    filename=str(pathlib.Path(__file__).parent / "debug-stdio.log"),
    filemode="w",
    format="%(asctime)s | %(name)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s",
    level=logging.DEBUG,
)
log = logging.getLogger("debug.log")

HEADER_PATTERN = re.compile(r"Content-Length:\s+(?P<length>\d+)".encode())


def process_init_request(msg: dap.InitializeRequest) -> dap.InitializeResponse:
    return dap.InitializeResponse(
        seq=1,
        request_seq=msg.seq,
        success=True,
        message=None,
        capabilities=dap.Capabilities(),
    )


def process_launch_request(msg: dap.LaunchRequest) -> dap.LaunchResponse:
    return dap.LaunchResponse(
        seq=2,
        request_seq=msg.seq,
        success=True,
        message=None,
    )


def pack_msg(msg: dap.ProtocolMessage) -> bytes:
    data: t.Dict[str, t.Any] = {}
    msg.pack(data)
    return json.dumps(data).encode()


def main() -> None:
    log.info("starting")
    stdin = sys.stdin.buffer.raw
    stdout = sys.stdout.buffer.raw

    while True:
        length = 0
        while True:
            data = stdin.readline().strip()
            log.debug("STDIN: %s", stdin)
            if not data:
                break

            if m := HEADER_PATTERN.match(data):
                length = int(m.group("length"))

        log.debug("STDIN Length: %d", length)

        content = bytearray()
        while length:
            value = stdin.read(length)
            log.debug("STDIN RAW: '%s'", value.decode())
            length -= len(value)
            content += value

        raw_msg = content.decode()
        log.debug("STDIN: '%s'", raw_msg)
        msg = dap.unpack_message(raw_msg)

        resp: dap.Response
        if isinstance(msg, dap.InitializeRequest):
            resp = process_init_request(msg)

        elif isinstance(msg, dap.LaunchRequest):
            resp = process_launch_request(msg)

        else:
            raise NotImplementedError(type(msg).__name__)

        resp_data = pack_msg(resp)
        stdout.write(f"Content-Length: {len(resp_data)}\r\n".encode())
        stdout.write(b"\r\n")
        stdout.write(resp_data)

        if isinstance(msg, dap.LaunchRequest):
            req = dap.RunInTerminalRequest(
                seq=3,
                kind="integrated",
                cwd=str(pathlib.Path(__file__).parent),
                args=[
                    "python",
                    "-m",
                    "ansibug",
                    "launch",
                    "5678",
                    "main.yml",
                    "-vv",
                ],
                title="Ansible Debug Terminal",
            )
            req_data = pack_msg(req)
            stdout.write(f"Content-Length: {len(req_data)}\r\n".encode())
            stdout.write(b"\r\n")
            stdout.write(req_data)

    log.info("ending")


if __name__ == "__main__":
    try:
        debugpy.listen(("localhost", 5678))
        debugpy.wait_for_client()
        main()
    except:
        log.exception("Failure")
        raise
