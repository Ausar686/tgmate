"""Child process that runs one tool operation on untrusted input; started only by `sandbox`.

Reads a `sandbox.encode_request` request from stdin and writes the results to stdout as `sandbox.encode_blobs`. A
`ToolError` exits with `sandbox.TOOL_ERROR_STATUS` and its message on stderr; anything else keeps its traceback.
"""

import collections.abc as cabc
import dataclasses
import os
import pathlib
import resource
import sys

from tgmate.tools import sandbox
from tgmate.tools.errors import ToolError
from tgmate.tools.office import Office
from tgmate.tools.pdf import PDF, PageSize
from tgmate.tools.youtube import YouTube

MB = 1024 * 1024
# CPU time beyond the request's wall-clock timeout, so a worker the parent lost track of still stops.
CPU_LIMIT_MARGIN_SECONDS = 5
OUT_OF_MEMORY = "The file needs more memory than I allow for one conversion."


@dataclasses.dataclass(frozen=True)
class Limits:
    """Per-process limits for the worker, inherited by anything it starts."""

    # Enough for the largest legitimate job (a 50-megapixel image with transparency, decoded and converted); a bomb
    # past the pixel checks fails here instead of taking the machine's memory.
    memory_bytes: int = 2048 * MB
    # 0: no file can grow (pipes are unaffected), so a compromised worker can't add to the database or plant files.
    # It runs as the caller's user, though, so it could still truncate or delete files that user owns.
    file_bytes: int = 0
    # Enough for the interpreter's imports and native libraries.
    open_files: int = 64


@dataclasses.dataclass(frozen=True)
class Operation:
    run: cabc.Callable[..., list[bytes]]
    limits: Limits = Limits()


OPERATIONS: dict[str, Operation] = {
    "pdf.from_images": Operation(lambda inputs, page_size: [PDF._from_images(inputs, PageSize(page_size))]),
    "pdf.to_jpegs": Operation(lambda inputs, dpi: PDF._to_jpegs(inputs[0], dpi)),
    "pdf.page_count": Operation(lambda inputs: [str(PDF._page_count(inputs[0])).encode()]),
    "pdf.to_docx": Operation(lambda inputs: [PDF._to_docx(inputs[0])]),
    # LibreOffice writes its profile and the PDF into the job's directory, and opens many fonts and libraries.
    "office.to_pdf": Operation(
        lambda inputs, soffice, workdir: [Office._to_pdf(inputs[0], soffice, pathlib.Path(workdir))],
        Limits(file_bytes=sandbox.MAX_OUTPUT_BYTES, open_files=1024),
    ),
    # yt-dlp downloads into the job's directory and runs ffmpeg and Deno. Deno's V8 reserves tens of gigabytes of
    # address space up front and crashes below about 64 GB, so this limit is nominal: the container's memory limit
    # (docker-compose.yaml) bounds real use.
    "youtube.download": Operation(
        lambda inputs, workdir, **options: [YouTube._download(workdir=pathlib.Path(workdir), **options)],
        Limits(memory_bytes=64 * 1024 * MB, file_bytes=4096 * MB, open_files=1024),
    ),
}
# In force from the start, before the request says which operation's (tighter or equal) limits apply.
LOOSEST_LIMITS = Limits(
    **{
        field.name: max(getattr(operation.limits, field.name) for operation in OPERATIONS.values())
        for field in dataclasses.fields(Limits)
    }
)


def handle(request: bytes) -> sandbox.Result:
    """Run the request's operation in this process, answering as the worker process would."""
    operation, options, inputs, _ = sandbox.decode_request(request)
    try:
        outputs = OPERATIONS[operation].run(inputs, **options)
    except ToolError as exc:
        return sandbox.Result(sandbox.TOOL_ERROR_STATUS, b"", str(exc).encode())
    except MemoryError:
        return sandbox.Result(sandbox.TOOL_ERROR_STATUS, b"", OUT_OF_MEMORY.encode())
    return sandbox.Result(0, sandbox.encode_blobs(outputs), b"")


# `main` and `_limit_resources` run only in worker processes, out of coverage's sight; tests/tools/test_sandbox.py
# runs them for real.


def main() -> None:  # pragma: no cover
    # Keep stdout for the results alone: anything a library prints goes to stderr instead.
    results = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    # Limited before reading the request, then tightened to the operation's limits: lowering a limit is always allowed.
    _limit_resources(LOOSEST_LIMITS)
    request = sys.stdin.buffer.read()
    decoded = sandbox.decode_request(request)
    _limit_resources(OPERATIONS[decoded.operation].limits)
    cpu_seconds = int(decoded.timeout) + CPU_LIMIT_MARGIN_SECONDS
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    result = handle(request)
    results.write(result.stdout)
    results.flush()
    sys.stderr.buffer.write(result.stderr)
    sys.stderr.flush()
    sys.exit(result.returncode)


def _limit_resources(limits: Limits) -> None:  # pragma: no cover
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_bytes, limits.file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    except ValueError:
        # macOS refuses to lower RLIMIT_AS; the limit matters on Linux, where the bot runs.
        pass
    return None


if __name__ == "__main__":
    main()
