"""Child process that runs one tool operation on untrusted input; started only by `sandbox`.

Reads a `sandbox.encode_request` request from stdin and writes the results to stdout as `sandbox.encode_blobs`. A
`ToolError` exits with `sandbox.TOOL_ERROR_STATUS` and its message on stderr; anything else keeps its traceback.
"""

import collections.abc as cabc
import os
import resource
import sys

from tgmate.tools import sandbox
from tgmate.tools.errors import ToolError
from tgmate.tools.pdf import PDF, PageSize

# Enough for the largest legitimate job (a 50-megapixel image with transparency, decoded and converted); a bomb past
# the pixel checks fails here instead of taking the machine's memory.
MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
# A little over the parent's wall-clock timeout, so a worker the parent lost track of still stops.
CPU_LIMIT_SECONDS = sandbox.TIMEOUT_SECONDS + 5
# Enough for the interpreter's imports and native libraries; the worker reads only from stdin.
OPEN_FILES_LIMIT = 64
OUT_OF_MEMORY = "The file needs more memory than I allow for one conversion."

Operation = cabc.Callable[..., list[bytes]]

OPERATIONS: dict[str, Operation] = {
    "pdf.from_images": lambda inputs, page_size: [PDF._from_images(inputs, PageSize(page_size))],
    "pdf.to_jpegs": lambda inputs, dpi: PDF._to_jpegs(inputs[0], dpi),
    "pdf.page_count": lambda inputs: [str(PDF._page_count(inputs[0])).encode()],
}


def handle(request: bytes) -> sandbox.Result:
    """Run the request's operation in this process, answering as the worker process would."""
    operation, options, inputs = sandbox.decode_request(request)
    try:
        outputs = OPERATIONS[operation](inputs, **options)
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
    _limit_resources()
    result = handle(sys.stdin.buffer.read())
    results.write(result.stdout)
    results.flush()
    sys.stderr.buffer.write(result.stderr)
    sys.stderr.flush()
    sys.exit(result.returncode)


def _limit_resources() -> None:  # pragma: no cover
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS + 1))
    # No file writes at all (pipes are unaffected), so a compromised worker can't tamper with the database.
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (OPEN_FILES_LIMIT, OPEN_FILES_LIMIT))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except ValueError:
        # macOS refuses to lower RLIMIT_AS; the limit matters on Linux, where the bot runs.
        pass
    return None


if __name__ == "__main__":
    main()
