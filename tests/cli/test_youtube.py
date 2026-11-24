import pathlib
import typing as t

import pytest
from typer.testing import CliRunner

from tests.terminal import plain
from tgmate.cli.app import app
from tgmate.tools.errors import ToolError
from tgmate.tools.youtube import Media, MediaFormat, YouTube

runner = CliRunner()
URL = "https://youtu.be/jNQXAC9IVRw"


@pytest.fixture(autouse=True)
def downloads(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, MediaFormat, dict]]:
    """Fakes the download (tested with the tool): records each call and leaves a file in the job's directory."""
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, MediaFormat, dict]] = []

    def download(url: str, media_format: MediaFormat, directory: pathlib.Path, **options: t.Any) -> Media:
        calls.append((url, media_format, options))
        path = directory / f"jNQXAC9IVRw.{media_format}"
        path.write_bytes(f"the {media_format}".encode())
        return Media(path, "Me at the zoo: the first video", "jawed", 19)

    monkeypatch.setattr(YouTube, "download", staticmethod(download))
    return calls


def test_youtube_to_mp3_names_the_file_after_the_video(
    tmp_path: pathlib.Path, downloads: list[tuple[str, MediaFormat, dict]]
) -> None:
    result = runner.invoke(app, ["youtube-to-mp3", URL])

    assert result.exit_code == 0
    assert result.stdout.strip() == "Me at the zoo the first video.mp3"
    assert (tmp_path / "Me at the zoo the first video.mp3").read_bytes() == b"the mp3"
    assert downloads == [(URL, MediaFormat.MP3, {})]


def test_youtube_to_mp4_takes_an_output_and_a_height(
    tmp_path: pathlib.Path, downloads: list[tuple[str, MediaFormat, dict]]
) -> None:
    result = runner.invoke(app, ["youtube-to-mp4", URL, "-o", "zoo.mp4", "--max-height", "1080"])

    assert result.exit_code == 0
    assert (tmp_path / "zoo.mp4").read_bytes() == b"the mp4"
    assert downloads == [(URL, MediaFormat.MP4, {"max_height": 1080})]


def test_an_existing_output_is_kept_and_nothing_is_downloaded(
    tmp_path: pathlib.Path, downloads: list[tuple[str, MediaFormat, dict]]
) -> None:
    (tmp_path / "zoo.mp3").write_bytes(b"keep")

    result = runner.invoke(app, ["youtube-to-mp3", URL, "-o", "zoo.mp3"])

    assert result.exit_code == 2
    assert "--force" in plain(result.stderr)
    assert (tmp_path / "zoo.mp3").read_bytes() == b"keep"
    assert downloads == []


def test_a_title_named_file_that_exists_is_kept_without_force(tmp_path: pathlib.Path) -> None:
    # Only known after the download, so the check comes after it.
    (tmp_path / "Me at the zoo the first video.mp3").write_bytes(b"keep")

    result = runner.invoke(app, ["youtube-to-mp3", URL])

    assert result.exit_code == 2
    assert (tmp_path / "Me at the zoo the first video.mp3").read_bytes() == b"keep"


def test_force_overwrites(tmp_path: pathlib.Path) -> None:
    (tmp_path / "zoo.mp4").write_bytes(b"old")

    result = runner.invoke(app, ["youtube-to-mp4", URL, "-o", "zoo.mp4", "-f"])

    assert result.exit_code == 0
    assert (tmp_path / "zoo.mp4").read_bytes() == b"the mp4"


@pytest.mark.parametrize("height", ["100", "4320"])
def test_height_out_of_range_is_a_usage_error(height: str, downloads: list[tuple[str, MediaFormat, dict]]) -> None:
    result = runner.invoke(app, ["youtube-to-mp4", URL, "--max-height", height])

    assert result.exit_code == 2
    assert downloads == []


def test_a_refusal_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    def refuse(*args: t.Any, **kwargs: t.Any) -> Media:
        raise ToolError("YouTube refused: Private video")

    monkeypatch.setattr(YouTube, "download", staticmethod(refuse))

    result = runner.invoke(app, ["youtube-to-mp3", URL])

    assert result.exit_code == 1
    assert result.stderr.strip() == "Error: YouTube refused: Private video"
    assert list(tmp_path.iterdir()) == []
