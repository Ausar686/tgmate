"""Run a tool operation on untrusted input in a separate, resource-limited process (see `worker`).

Parsing PDFs and images runs native code (PDFium, Pillow's decoders) on files users send. In a child process a crash
fails one conversion instead of the bot, a hang is killed on timeout (a thread can't be), a decompression bomb hits the
child's memory limit, and the child never sees the bot's settings or secrets.
"""

import contextlib
import json
import logging
import os
import selectors
import signal
import struct
import subprocess  # nosec B404
import sys
import tempfile
import time
import typing as t

from tgmate.tools.errors import ToolError

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120
# The most output read back; a compromised child could otherwise fill the caller's memory.
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024
# The worker's exit status when it refused the input with a `ToolError`, whose message is then all of stderr.
TOOL_ERROR_STATUS = 3
ERROR_CHARS = 300
STDERR_TAIL_BYTES = 64 * 1024
REAP_TIMEOUT_SECONDS = 5

FAILED = "The conversion failed unexpectedly."

# `-I`: no PYTHON* variables, user site-packages or current directory on the import path.
_COMMAND = (sys.executable, "-I", "-m", "tgmate.tools.worker")
_LENGTH = struct.Struct(">Q")
_CHUNK_BYTES = 64 * 1024

Options = dict[str, str | int]


class Result(t.NamedTuple):
    returncode: int
    stdout: bytes
    stderr: bytes


def run(
    operation: str, inputs: t.Sequence[bytes], options: Options, outputs: range, *, workdir: bool = False
) -> list[bytes]:
    """The blobs the worker's `operation` returns for `inputs`; raises `ToolError` for anything but a clean result.

    With `workdir`, the operation also gets an empty directory as the `workdir` option. The caller creates and removes
    it, so it's cleaned up even when the worker is killed.
    """
    if workdir:
        with tempfile.TemporaryDirectory(prefix="tgmate-") as directory:
            return run(operation, inputs, {**options, "workdir": directory}, outputs)
    result = _execute(encode_request(operation, options, inputs))
    if result.returncode == TOOL_ERROR_STATUS:
        raise ToolError(result.stderr.decode(errors="replace")[:ERROR_CHARS])
    try:
        if result.returncode != 0:
            raise ValueError(_failure(result))
        blobs = decode_blobs(result.stdout)
        if len(blobs) not in outputs:
            raise ValueError(f"worker returned {len(blobs)} results")
    except ValueError as exc:
        log.warning("%s failed: %s", operation, exc)
        raise ToolError(FAILED) from None
    return blobs


def encode_request(operation: str, options: Options, inputs: t.Sequence[bytes]) -> bytes:
    header = json.dumps({"operation": operation, "options": options}).encode()
    return encode_blobs([header, *inputs])


def decode_request(request: bytes) -> tuple[str, Options, list[bytes]]:
    header, *inputs = decode_blobs(request)
    fields = json.loads(header)
    return fields["operation"], fields["options"], inputs


def encode_blobs(blobs: t.Iterable[bytes]) -> bytes:
    return b"".join(_LENGTH.pack(len(blob)) + blob for blob in blobs)


def decode_blobs(data: bytes) -> list[bytes]:
    """Parse length-prefixed blobs, rejecting anything `encode_blobs` can't produce."""
    blobs = []
    offset = 0
    while offset < len(data):
        if offset + _LENGTH.size > len(data):
            raise ValueError("output is truncated")
        (size,) = _LENGTH.unpack_from(data, offset)
        offset += _LENGTH.size
        if offset + size > len(data):
            raise ValueError("output is truncated")
        blobs.append(data[offset : offset + size])
        offset += size
    return blobs


def _execute(request: bytes) -> Result:
    """Run the worker on `request`. Tests swap this for an in-process call to `worker.handle`."""
    # Our own worker module, run with an argument list and no shell. An empty environment: the worker needs no settings
    # and must not hold the bot's token. Its own process group lets a kill reach anything it starts, too.
    process = subprocess.Popen(  # nosec B603
        _COMMAND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={},
        start_new_session=True,
    )
    try:
        stdout, stderr = _communicate(process, request)
    finally:
        _kill(process)
        try:
            process.wait(REAP_TIMEOUT_SECONDS)
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
    return Result(process.returncode, stdout, stderr)


def _communicate(process: subprocess.Popen[bytes], request: bytes) -> tuple[bytes, bytes]:
    """Feed the worker and read its output until both pipes close, within the timeout and the output limit.

    Like `Popen.communicate`, but it stops reading (and the caller kills the worker) past `MAX_OUTPUT_BYTES`, and keeps
    only the tail of stderr.
    """
    deadline = time.monotonic() + TIMEOUT_SECONDS
    pending = memoryview(request)
    stdout, stderr = bytearray(), b""
    with selectors.DefaultSelector() as selector:
        os.set_blocking(process.stdin.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolError(f"The conversion took longer than {TIMEOUT_SECONDS} seconds; try a smaller file.")
            for key, _ in selector.select(remaining):
                if key.fileobj is process.stdin:
                    try:
                        pending = pending[os.write(key.fd, pending[:_CHUNK_BYTES]) :]
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        # The worker exited without reading everything; its exit status tells why.
                        pending = pending[:0]
                    if not pending:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                    continue
                chunk = os.read(key.fd, _CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                elif key.fileobj is process.stdout:
                    stdout += chunk
                    if len(stdout) > MAX_OUTPUT_BYTES:
                        raise ToolError(f"The result would be over {MAX_OUTPUT_BYTES // (1024 * 1024)} MB.")
                else:
                    stderr = (stderr + chunk)[-STDERR_TAIL_BYTES:]
    return bytes(stdout), stderr


def _kill(process: subprocess.Popen[bytes]) -> None:
    """Kill the worker's process group, which also stops anything it started."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    return None


def _failure(result: Result) -> str:
    if result.returncode < 0:
        return f"worker was killed by {signal.Signals(-result.returncode).name}"
    lines = result.stderr.decode(errors="replace").strip().splitlines()
    status = f"worker exited with {result.returncode}"
    return f"{status}: {lines[-1][:ERROR_CHARS]}" if lines else status
