import io
import logging
import os
import pathlib
import sys
import time

import pytest
from PIL import Image

from tests.images import close_to, make_image, pdf_page_image
from tgmate.tools import sandbox, worker
from tgmate.tools.errors import ToolError
from tgmate.tools.pdf import PDF, PageSize

pytestmark = pytest.mark.real_sandbox

BLUE = (0, 0, 255)


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> object:
    """Swap the worker for a Python script; its own `handle`/`main` are importable for scripts that wrap them."""

    def use(script: str) -> None:
        monkeypatch.setattr(sandbox, "_COMMAND", (sys.executable, "-c", script))
        return None

    return use


def wrapped_worker(operation: str) -> str:
    """A script running the real worker `main` with one extra operation, `test`, defined by `operation`."""
    register = "worker.OPERATIONS['test'] = worker.Operation(test)"
    return f"from tgmate.tools import worker\n{operation}\n{register}\nworker.main()"


def run_test_operation() -> list[bytes]:
    return sandbox.run("test", [b"input"], {}, outputs=range(0, 10))


# --- the real worker ---


def test_operations_round_trip_through_a_worker_process() -> None:
    pdf = PDF.from_images([make_image(size=(30, 60), color="blue")] * 2, PageSize.A4)

    assert PDF.page_count(pdf) == 2
    pages = PDF.to_jpegs(pdf, dpi=72)
    assert [Image.open(io.BytesIO(page)).size for page in pages] == [(596, 842)] * 2
    assert close_to(pdf_page_image(pdf).getpixel((297, 420)), BLUE)


def test_a_refusal_in_the_worker_is_the_callers_tool_error() -> None:
    with pytest.raises(ToolError, match="^This isn't a PDF I can read.$"):
        PDF.to_jpegs(b"just text")


# --- containment, with stand-in workers ---


def test_a_hanging_worker_is_killed(stand_in, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "TIMEOUT_SECONDS", 0.5)
    stand_in("import time; time.sleep(60)")

    started = time.monotonic()
    with pytest.raises(ToolError, match=r"^The conversion took longer than 0\.5 seconds; try a smaller file\.$"):
        run_test_operation()

    assert time.monotonic() - started < 5


def test_processes_the_worker_starts_are_killed_with_it(
    stand_in, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setattr(sandbox, "TIMEOUT_SECONDS", 1)
    pid_file = tmp_path / "pid"
    stand_in(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)"
    )

    with pytest.raises(ToolError, match="took longer than"):
        run_test_operation()

    pid = int(pid_file.read_text())
    assert eventually_gone(pid), f"process {pid}, started by the worker, is still running"


def eventually_gone(pid: int) -> bool:
    """Whether the process exits within a few seconds; a killed process may linger as a zombie until init reaps it."""
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        status = pathlib.Path(f"/proc/{pid}/stat")
        # Linux shows the state after the parenthesised command name; elsewhere, wait for the process to be reaped.
        if status.exists() and status.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return True
        time.sleep(0.05)
    return False


def test_a_crashing_worker_fails_only_the_conversion(stand_in, caplog: pytest.LogCaptureFixture) -> None:
    stand_in("import os; os.abort()")

    with caplog.at_level(logging.WARNING), pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        run_test_operation()

    assert "killed by SIGABRT" in caplog.text


def test_an_unexpected_error_is_logged_with_the_last_line_of_its_traceback(
    stand_in, caplog: pytest.LogCaptureFixture
) -> None:
    stand_in(wrapped_worker("def test(inputs):\n    raise RuntimeError('boom')"))

    with caplog.at_level(logging.WARNING), pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        run_test_operation()

    assert "worker exited with 1: RuntimeError: boom" in caplog.text


def test_the_worker_gets_no_secrets(stand_in, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    stand_in(wrapped_worker("import os\ndef test(inputs):\n    return [repr(sorted(os.environ)).encode()]"))

    [environment] = run_test_operation()

    assert b"TELEGRAM_BOT_TOKEN" not in environment


def test_the_worker_cannot_make_files_grow(stand_in, tmp_path: pathlib.Path) -> None:
    target = tmp_path / "tampered"
    target.write_bytes(b"")
    write = f"os.write(os.open({str(target)!r}, os.O_WRONLY | os.O_APPEND), b'x')"
    stand_in(wrapped_worker(f"import os\ndef test(inputs):\n    {write}\n    return []"))

    with pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        run_test_operation()

    assert target.read_bytes() == b""


def test_what_libraries_print_cannot_corrupt_the_results(stand_in) -> None:
    stand_in(wrapped_worker("def test(inputs):\n    print('a library talking')\n    return [b'result']"))

    assert run_test_operation() == [b"result"]


def test_the_worker_reads_its_input_and_options(stand_in) -> None:
    stand_in(wrapped_worker("def test(inputs, scale):\n    return [blob * scale for blob in inputs]"))

    assert sandbox.run("test", [b"ab", b"c"], {"scale": 2}, outputs=range(2, 3)) == [b"abab", b"cc"]


@pytest.mark.parametrize("script", ["import sys; sys.stdout.buffer.write(b'x' * 1000)", "import time; time.sleep(60)"])
def test_a_flooding_worker_is_stopped(stand_in, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    monkeypatch.setattr(sandbox, "MAX_OUTPUT_BYTES", 100)
    monkeypatch.setattr(sandbox, "TIMEOUT_SECONDS", 5)
    stand_in(f"import sys; sys.stdout.buffer.write(b'x' * 1000); sys.stdout.flush(); {script}")

    started = time.monotonic()
    with pytest.raises(ToolError, match=r"^The result would be over 0 MB\.$"):
        run_test_operation()

    assert time.monotonic() - started < 4


def test_a_worker_that_ignores_its_input_is_not_an_error_by_itself(stand_in) -> None:
    # Bigger than a pipe's buffer, so writing it fails once the worker has exited.
    stand_in("pass")

    assert sandbox.run("test", [b"x" * 1_000_000], {}, outputs=range(0, 1)) == []


@pytest.mark.parametrize(
    "output",
    [sandbox.encode_blobs([b"a", b"b"]), b"\x00\x00\x00", sandbox.encode_blobs([b"abc"])[:-1]],
    ids=["too many results", "truncated length", "truncated blob"],
)
def test_output_a_well_behaved_worker_cannot_produce_is_refused(stand_in, output: bytes) -> None:
    stand_in(f"import sys; sys.stdout.buffer.write({output!r})")

    with pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        sandbox.run("test", [], {}, outputs=range(1, 2))


def test_a_page_count_that_is_not_a_number_is_refused(stand_in) -> None:
    stand_in(f"import sys; sys.stdout.buffer.write({sandbox.encode_blobs([b'many'])!r})")

    with pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        PDF.page_count(b"%PDF")


def test_a_long_refusal_is_cut(stand_in) -> None:
    stand_in(f"import sys; sys.stderr.write('x' * 1000); sys.exit({sandbox.TOOL_ERROR_STATUS})")

    with pytest.raises(ToolError) as refused:
        run_test_operation()

    assert str(refused.value) == "x" * sandbox.ERROR_CHARS


# --- in-process request handling ---


def test_running_out_of_memory_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def exhausting(inputs: list[bytes]) -> list[bytes]:
        raise MemoryError

    monkeypatch.setitem(worker.OPERATIONS, "test", worker.Operation(exhausting))

    result = worker.handle(sandbox.encode_request("test", {}, []))

    assert result == (sandbox.TOOL_ERROR_STATUS, b"", worker.OUT_OF_MEMORY.encode())


def test_the_limits_before_the_request_allow_every_operations_limits() -> None:
    for operation in worker.OPERATIONS.values():
        assert operation.limits.memory_bytes <= worker.LOOSEST_LIMITS.memory_bytes
        assert operation.limits.file_bytes <= worker.LOOSEST_LIMITS.file_bytes
        assert operation.limits.open_files <= worker.LOOSEST_LIMITS.open_files
    assert worker.LOOSEST_LIMITS.open_files == 1024
