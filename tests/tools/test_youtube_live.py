"""Real downloads from YouTube, for checking a yt-dlp update against a link that broke: run with
`TGMATE_NETWORK_TESTS=1 pytest tests/tools/test_youtube_live.py` where ffmpeg is installed. Skipped otherwise, since
tests never touch the network by default."""

import os
import pathlib

import pytest

from tgmate.tools.youtube import MediaFormat, YouTube

pytestmark = [
    pytest.mark.real_sandbox,
    pytest.mark.skipif(os.environ.get("TGMATE_NETWORK_TESTS") != "1", reason="set TGMATE_NETWORK_TESTS=1"),
]

# "Me at the zoo", the first video on YouTube: 19 seconds and unlikely to disappear.
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.mark.parametrize(
    ("media_format", "signature"), [(MediaFormat.MP3, b"ID3"), (MediaFormat.MP4, b"ftyp")], ids=["mp3", "mp4"]
)
def test_a_real_video_downloads(tmp_path: pathlib.Path, media_format: MediaFormat, signature: bytes) -> None:
    media = YouTube.download(URL, media_format, tmp_path)

    assert (media.title, media.uploader, media.duration) == ("Me at the zoo", "jawed", 19)
    assert signature in media.path.read_bytes()[:16]
