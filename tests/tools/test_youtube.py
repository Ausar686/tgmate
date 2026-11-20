import os
import pathlib
import re
import typing as t

import pytest
import yt_dlp
import yt_dlp.globals

from tgmate.tools import sandbox
from tgmate.tools.errors import ToolError
from tgmate.tools.youtube import NOT_A_VIDEO, Media, MediaFormat, YouTube, safe_file_stem

VIDEO = "jNQXAC9IVRw"
INFO = {"_type": "video", "id": VIDEO, "title": "Me at the zoo", "uploader": "jawed", "duration": 19}


class FakeDownloader:
    """Stands in for `yt_dlp.YoutubeDL` (YouTube is the network): records its options, returns `info` and writes the
    file yt-dlp would, `size` bytes long."""

    created: t.ClassVar[list[FakeDownloader]] = []
    info: t.ClassVar[dict] = INFO
    size: t.ClassVar[int] = 1000
    error: t.ClassVar[Exception | None] = None

    def __init__(self, options: dict) -> None:
        self.options = options
        self.urls: list[str] = []
        self.downloaded = False
        self.created.append(self)

    def __enter__(self) -> FakeDownloader:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict:
        assert download is False
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return dict(self.info)

    def process_ie_result(self, info: dict, download: bool) -> dict:
        self.downloaded = download
        extension = "mp3" if self.options.get("postprocessors", [{}])[0].get("key") == "FFmpegExtractAudio" else "mp4"
        name = self.options["outtmpl"]["default"].replace("%(ext)s", extension)
        (pathlib.Path(self.options["paths"]["home"]) / name).write_bytes(b"\0" * self.size)
        return info


@pytest.fixture
def downloader(monkeypatch: pytest.MonkeyPatch) -> type[FakeDownloader]:
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeDownloader)
    monkeypatch.setattr(FakeDownloader, "created", [])
    monkeypatch.setattr(YouTube, "ffmpeg", staticmethod(lambda: "/opt/ffmpeg/bin"))
    # The worker turns plugins off for its whole process; keep that out of other tests.
    monkeypatch.setattr(yt_dlp.globals.plugin_dirs, "value", list(yt_dlp.globals.plugin_dirs.value))
    return FakeDownloader


def download(tmp_path: pathlib.Path, media_format: MediaFormat = MediaFormat.MP3, **kwargs: t.Any) -> Media:
    return YouTube.download(f"https://youtu.be/{VIDEO}", media_format, tmp_path, **kwargs)


# --- links ---


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO}",
        f"youtube.com/watch?v={VIDEO}&list=PL123&t=42s",
        f"  http://m.youtube.com/watch?feature=share&v={VIDEO}  ",
        f"https://music.youtube.com/watch?v={VIDEO}",
        f"https://youtu.be/{VIDEO}?si=abc",
        f"https://www.youtube.com/shorts/{VIDEO}",
        f"https://www.youtube.com/live/{VIDEO}",
        f"https://www.youtube.com/embed/{VIDEO}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={VIDEO}",
    ],
)
def test_video_links_name_their_video(url: str) -> None:
    assert YouTube.video_id(url) == VIDEO


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=jNQXAC9IVRw",
        "https://youtube.com.evil.example/watch?v=jNQXAC9IVRw",
        # The host is evil.example: everything before `@` is a username.
        "https://www.youtube.com@evil.example/watch?v=jNQXAC9IVRw",
        "https://user:pass@www.youtube.com/watch?v=jNQXAC9IVRw",
        "ftp://www.youtube.com/watch?v=jNQXAC9IVRw",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@channel",
        "https://www.youtube.com/watch?v=tooShort",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw/../x",
        "https://youtu.be/jNQXAC9IVRw/extra",
        "https://[::1/watch?v=jNQXAC9IVRw",
        "",
    ],
)
def test_anything_but_a_single_video_link_is_refused(url: str) -> None:
    with pytest.raises(ToolError, match=f"^{re.escape(NOT_A_VIDEO)}$"):
        YouTube.video_id(url)


# --- downloading ---


def test_mp3_downloads_the_best_audio_and_converts_it(tmp_path: pathlib.Path, downloader: type[FakeDownloader]) -> None:
    media = download(tmp_path)

    assert media == Media(tmp_path / f"{VIDEO}.mp3", "Me at the zoo", "jawed", 19)
    assert media.file_name == "Me at the zoo.mp3"
    [used] = downloader.created
    assert used.urls == [f"https://www.youtube.com/watch?v={VIDEO}"]
    assert used.downloaded
    assert used.options["format"] == "bestaudio/best"
    assert used.options["postprocessors"][0] == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192",
    }


def test_mp4_prefers_h264_and_aac_up_to_the_height(tmp_path: pathlib.Path, downloader: type[FakeDownloader]) -> None:
    media = download(tmp_path, MediaFormat.MP4, max_height=480)

    assert media.path == tmp_path / f"{VIDEO}.mp4"
    [used] = downloader.created
    assert used.options["format_sort"] == ["res:480", "vcodec:h264", "acodec:aac"]
    assert used.options["merge_output_format"] == "mp4"


def test_downloads_are_locked_to_youtube_and_the_job_directory(
    tmp_path: pathlib.Path, downloader: type[FakeDownloader]
) -> None:
    download(tmp_path, max_bytes=50 * 1024 * 1024)

    options = downloader.created[0].options
    assert options["allowed_extractors"] == ["youtube"]
    assert options["noplaylist"] is True
    assert options["cachedir"] is False
    assert options["paths"] == {"home": str(tmp_path), "temp": str(tmp_path)}
    assert options["outtmpl"] == {"default": f"{VIDEO}.%(ext)s"}
    assert options["max_filesize"] == 50 * 1024 * 1024
    assert options["ffmpeg_location"] == "/opt/ffmpeg/bin"
    deno = options["js_runtimes"]["deno"]["path"]
    assert os.access(deno, os.X_OK)
    assert yt_dlp.globals.plugin_dirs.value == []


@pytest.mark.parametrize(
    ("info", "message"),
    [
        ({"live_status": "is_live"}, "Live streams and premieres"),
        ({"live_status": "is_upcoming"}, "Live streams and premieres"),
        ({"is_live": True}, "Live streams and premieres"),
        ({"duration": 3 * 60 * 60 + 1}, r"3\.0 hours long; the limit is 3 hours"),
        ({"duration": None}, "doesn't say how long"),
        ({"_type": "playlist"}, re.escape(NOT_A_VIDEO)),
        (
            {"requested_formats": [{"filesize": 30 * 1024 * 1024}, {"filesize_approx": 25 * 1024 * 1024}]},
            "about 55 MB; the limit is 50 MB",
        ),
    ],
)
def test_videos_are_checked_before_downloading(
    tmp_path: pathlib.Path,
    downloader: type[FakeDownloader],
    monkeypatch: pytest.MonkeyPatch,
    info: dict,
    message: str,
) -> None:
    monkeypatch.setattr(FakeDownloader, "info", {**INFO, **info})

    with pytest.raises(ToolError, match=message):
        download(tmp_path, max_bytes=50 * 1024 * 1024)

    assert not downloader.created[0].downloaded


def test_youtubes_refusal_is_reported_without_yt_dlps_prefixes(
    tmp_path: pathlib.Path, downloader: type[FakeDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    message = f"\x1b[0;31mERROR:\x1b[0m [youtube] {VIDEO}: Private video. Sign in if you've been granted access"
    error = yt_dlp.utils.DownloadError(message)
    monkeypatch.setattr(FakeDownloader, "error", error)

    with pytest.raises(ToolError, match=r"^YouTube refused: Private video\. Sign in if you've been granted access$"):
        download(tmp_path)


@pytest.mark.parametrize(("failures", "succeeds"), [(1, True), (2, False)])
def test_a_forbidden_stream_is_tried_once_more_from_scratch(
    tmp_path: pathlib.Path,
    downloader: type[FakeDownloader],
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
    succeeds: bool,
) -> None:
    errors = [yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")] * failures
    real = FakeDownloader.process_ie_result

    def forbidden_at_first(self: FakeDownloader, info: dict, download: bool) -> dict:
        if errors:
            raise errors.pop()
        return real(self, info, download)

    monkeypatch.setattr(FakeDownloader, "process_ie_result", forbidden_at_first)

    if succeeds:
        assert download(tmp_path).path.exists()
    else:
        with pytest.raises(ToolError, match="^YouTube refused: unable to download video data: HTTP Error 403"):
            download(tmp_path)
    assert len(downloader.created) == 2


def test_a_file_yt_dlp_skipped_for_its_size_is_reported(
    tmp_path: pathlib.Path, downloader: type[FakeDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    # yt-dlp skips a format over `max_filesize` without an error, so no file appears.
    monkeypatch.setattr(FakeDownloader, "process_ie_result", lambda self, info, download: info)

    with pytest.raises(ToolError, match="^The MP3 would be over 1 MB.$"):
        download(tmp_path, max_bytes=1024 * 1024)


def test_a_result_over_the_limit_is_refused(
    tmp_path: pathlib.Path, downloader: type[FakeDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeDownloader, "size", 2 * 1024 * 1024)

    with pytest.raises(ToolError, match="^The MP4 is 2 MB; the limit is 1 MB.$"):
        download(tmp_path, MediaFormat.MP4, max_bytes=1024 * 1024)


def test_a_missing_uploader_and_title_fall_back(
    tmp_path: pathlib.Path, downloader: type[FakeDownloader], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeDownloader, "info", {**INFO, "title": None, "uploader": ["not", "a", "name"]})

    media = download(tmp_path)

    assert (media.title, media.uploader, media.file_name) == (VIDEO, None, f"{VIDEO}.mp3")


@pytest.mark.parametrize("height", [YouTube.MIN_HEIGHT - 1, YouTube.MAX_HEIGHT + 1])
def test_height_out_of_range_is_refused(tmp_path: pathlib.Path, downloader: type[FakeDownloader], height: int) -> None:
    with pytest.raises(ToolError, match="height must be between"):
        download(tmp_path, MediaFormat.MP4, max_height=height)

    assert downloader.created == []


def test_missing_ffmpeg_is_reported(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ToolError, match="ffmpeg isn't installed"):
        download(tmp_path)


def test_ffmpeg_is_found_with_ffprobe_beside_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/opt/media/bin/{name}")

    assert YouTube.ffmpeg() == "/opt/media/bin"


# --- what the worker reports, checked like any of its output ---


@pytest.mark.parametrize(
    "metadata",
    [b"not json", b'{"title": 1, "uploader": null, "duration": 19}', b'{"title": "x", "duration": 19}'],
)
def test_a_malformed_report_is_a_failure(tmp_path: pathlib.Path, metadata: bytes) -> None:
    (tmp_path / "x.mp3").write_bytes(b"audio")

    with pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        YouTube._read_metadata(metadata, tmp_path / "x.mp3", 100)


@pytest.mark.parametrize("problem", ["missing", "symlink", "too large"])
def test_a_report_without_a_proper_file_is_a_failure(tmp_path: pathlib.Path, problem: str) -> None:
    path = tmp_path / "x.mp3"
    if problem == "symlink":
        (tmp_path / "elsewhere").write_bytes(b"audio")
        path.symlink_to(tmp_path / "elsewhere")
    elif problem == "too large":
        path.write_bytes(b"\0" * 101)

    with pytest.raises(ToolError, match=f"^{sandbox.FAILED}$"):
        YouTube._read_metadata(b'{"title": "x", "uploader": null, "duration": 1}', path, 100)


@pytest.mark.parametrize(
    ("title", "stem"),
    [
        ("Me at the zoo", "Me at the zoo"),
        ('AC/DC: "Back in Black" <live>?', "AC DC Back in Black live"),
        ("../../etc/passwd", "etc passwd"),
        ("tab\tand\nnewline", "tab and newline"),
        ("...", ""),
        ("Привет, мир 👋", "Привет, мир 👋"),
        ("x" * 300, "x" * 120),
    ],
)
def test_titles_become_safe_file_names(title: str, stem: str) -> None:
    assert safe_file_stem(title) == stem
