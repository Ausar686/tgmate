"""`tgmate youtube-to-mp3` and `tgmate youtube-to-mp4`."""

import pathlib
import tempfile
import typing as t

import typer

from tgmate.cli.files import copy_output, refuse_existing
from tgmate.tools.youtube import MediaFormat, YouTube

Url = t.Annotated[str, typer.Argument(help="YouTube video link (youtube.com/watch?v=…, youtu.be/…, shorts).")]
Force = t.Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output file.")]


def output_option(extension: str) -> t.Any:
    return typer.Option(
        "--output", "-o", dir_okay=False, help=f"File to write (default: the video's title, .{extension})."
    )


def youtube_to_mp3(
    url: Url,
    output: t.Annotated[pathlib.Path | None, output_option("mp3")] = None,
    force: Force = False,
) -> None:
    """Download a YouTube video's audio as MP3 (needs ffmpeg)."""
    _download(url, MediaFormat.MP3, output, force)


def youtube_to_mp4(
    url: Url,
    output: t.Annotated[pathlib.Path | None, output_option("mp4")] = None,
    max_height: t.Annotated[
        int,
        typer.Option(
            min=YouTube.MIN_HEIGHT, max=YouTube.MAX_HEIGHT, help="Highest resolution, by the shorter side (720 = 720p)."
        ),
    ] = YouTube.DEFAULT_MAX_HEIGHT,
    force: Force = False,
) -> None:
    """Download a YouTube video as MP4, preferring H.264 and AAC (needs ffmpeg)."""
    _download(url, MediaFormat.MP4, output, force, max_height=max_height)


def _download(
    url: str, media_format: MediaFormat, output: pathlib.Path | None, force: bool, **options: t.Any
) -> None:
    if output is not None:
        # Before downloading, which can take minutes. Without `--output` the name comes from the video's title, known
        # only once it's downloaded.
        refuse_existing([output], force=force)
    with tempfile.TemporaryDirectory(prefix="tgmate-") as directory:
        media = YouTube.download(url, media_format, pathlib.Path(directory), **options)
        copy_output(media.path, output or pathlib.Path(media.file_name), force=force)
