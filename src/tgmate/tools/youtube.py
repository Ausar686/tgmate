"""YouTube videos as MP3 audio or MP4 video, downloaded by yt-dlp (with Deno and ffmpeg) in the sandbox."""

import dataclasses
import enum
import json
import os
import pathlib
import re
import shutil
import unicodedata
import urllib.parse

from tgmate.tools import sandbox
from tgmate.tools.errors import ToolError

MB = 1024 * 1024
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
# Hosts whose links name a video in the path (`/shorts/ID`, `youtu.be/ID`) or in `?v=ID`.
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
SHORT_HOSTS = {"youtu.be"}
VIDEO_PATHS = {"shorts", "live", "embed", "v"}
NOT_A_VIDEO = "Send a link to a YouTube video, like youtube.com/watch?v=… or youtu.be/…"
# Characters no file system or Telegram client handles well in a file name.
UNSAFE_FILE_CHARACTERS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


class MediaFormat(enum.StrEnum):
    MP3 = "mp3"
    MP4 = "mp4"


@dataclasses.dataclass(frozen=True)
class Media:
    """A downloaded video or its audio, with what YouTube says about it."""

    path: pathlib.Path
    title: str
    uploader: str | None
    duration: int

    @property
    def file_name(self) -> str:
        """The title as a file name, for front ends to save or send the file under."""
        return f"{safe_file_stem(self.title) or self.path.stem}{self.path.suffix}"


def safe_file_stem(title: str, limit: int = 120) -> str:
    stem = UNSAFE_FILE_CHARACTERS.sub(" ", unicodedata.normalize("NFC", title))
    return " ".join(stem.split())[:limit].strip(" .")


class YouTube:
    """Downloads one YouTube video as MP3 or MP4."""

    MAX_DURATION_SECONDS = 3 * 60 * 60
    DEFAULT_MAX_HEIGHT = 720
    MIN_HEIGHT, MAX_HEIGHT = 144, 2160
    # The self-hosted Bot API server's upload limit; front ends with a lower one pass it.
    MAX_BYTES = 2000 * MB
    TIMEOUT_SECONDS = 30 * 60
    MP3_BITRATE_KBPS = 192

    @classmethod
    def download(
        cls,
        url: str,
        media_format: MediaFormat,
        directory: pathlib.Path,
        *,
        max_height: int = DEFAULT_MAX_HEIGHT,
        max_bytes: int = MAX_BYTES,
    ) -> Media:
        """Download the video at `url` into `directory` (the caller's, and removed by it) as MP3 or MP4.

        Video is the best up to `max_height` (by its shorter side, so vertical videos aren't penalised), preferring
        H.264 and AAC, which every player handles. Refused with `ToolError`: anything but a single YouTube video, live
        streams and premieres, videos over `MAX_DURATION_SECONDS`, results over `max_bytes`, and what YouTube refuses.
        """
        if not cls.MIN_HEIGHT <= max_height <= cls.MAX_HEIGHT:
            raise ToolError(f"The height must be between {cls.MIN_HEIGHT} and {cls.MAX_HEIGHT} pixels.")
        video_id = cls.video_id(url)
        options: sandbox.Options = {
            "video_id": video_id,
            "media_format": media_format.value,
            "max_height": max_height,
            "max_bytes": max_bytes,
            "ffmpeg": cls.ffmpeg(),
        }
        [metadata] = sandbox.run(
            "youtube.download", [], options, outputs=range(1, 2), workdir=directory, timeout=cls.TIMEOUT_SECONDS
        )
        return cls._read_metadata(metadata, directory / f"{video_id}.{media_format}", max_bytes)

    @staticmethod
    def video_id(url: str) -> str:
        """The video's ID from a youtube.com or youtu.be link; refuses anything else with `ToolError`."""
        url = url.strip()
        try:
            parts = urllib.parse.urlsplit(url if "://" in url else f"https://{url}")
            host = parts.hostname
        except ValueError as exc:
            # A malformed address, such as an unclosed IPv6 bracket.
            raise ToolError(NOT_A_VIDEO) from exc
        if parts.scheme not in ("http", "https") or parts.username or parts.password or host is None:
            raise ToolError(NOT_A_VIDEO)
        segments = [segment for segment in parts.path.split("/") if segment]
        candidate = None
        if host in SHORT_HOSTS and len(segments) == 1:
            candidate = segments[0]
        elif host in YOUTUBE_HOSTS and segments == ["watch"]:
            candidate = urllib.parse.parse_qs(parts.query).get("v", [None])[0]
        elif host in YOUTUBE_HOSTS and len(segments) == 2 and segments[0] in VIDEO_PATHS:
            candidate = segments[1]
        if candidate is None or not VIDEO_ID.fullmatch(candidate):
            raise ToolError(NOT_A_VIDEO)
        return candidate

    @staticmethod
    def ffmpeg() -> str:
        """The folder holding ffmpeg and ffprobe; refuses with `ToolError` when they aren't installed."""
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            raise ToolError("ffmpeg isn't installed here, so I can't download from YouTube.")
        return os.path.dirname(ffmpeg)

    @staticmethod
    def _read_metadata(metadata: bytes, path: pathlib.Path, max_bytes: int) -> Media:
        """The worker's report, checked like any of its output: it parsed untrusted pages."""
        try:
            fields = json.loads(metadata)
            title, uploader, duration = fields["title"], fields["uploader"], fields["duration"]
            if not (isinstance(title, str) and isinstance(uploader, str | None) and isinstance(duration, int)):
                raise TypeError(fields)
        except (ValueError, KeyError, TypeError) as exc:
            raise ToolError(sandbox.FAILED) from exc
        if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
            raise ToolError(sandbox.FAILED)
        return Media(path, title, uploader, duration)

    # The operation itself, run by the sandbox's worker.

    @classmethod
    def _download(
        cls, video_id: str, media_format: str, max_height: int, max_bytes: int, ffmpeg: str, workdir: pathlib.Path
    ) -> bytes:
        # Imported here, in the worker only: yt-dlp is large and loads its extractors on import.
        import deno
        import yt_dlp
        import yt_dlp.globals

        # No plugins from anywhere on disk: only yt-dlp's own YouTube extractor runs.
        yt_dlp.globals.plugin_dirs.value = []
        # The worker's environment is empty; Deno needs a home for its cache.
        os.environ.setdefault("HOME", str(workdir))
        options = cls._options(video_id, MediaFormat(media_format), max_height, max_bytes, ffmpeg, workdir)
        options["js_runtimes"] = {"deno": {"path": deno.find_deno_bin()}}

        def fetch() -> dict:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                cls._check(info, max_bytes)
                downloader.process_ie_result(info, download=True)
            return info

        try:
            try:
                info = fetch()
            except yt_dlp.utils.DownloadError as exc:
                # YouTube sometimes answers a stream's address with 403 Forbidden; extracting again from scratch gets
                # fresh addresses, which usually work.
                if "HTTP Error 403" not in str(exc):
                    raise
                info = fetch()
        except yt_dlp.utils.DownloadError as exc:
            raise ToolError(cls._youtube_error(str(exc))) from None
        path = workdir / f"{video_id}.{media_format}"
        if not path.is_file():
            # yt-dlp skips formats over `max_filesize` without an error.
            raise ToolError(f"The {media_format.upper()} would be over {max_bytes // MB} MB.")
        if path.stat().st_size > max_bytes:
            size = path.stat().st_size / MB
            raise ToolError(f"The {media_format.upper()} is {size:.0f} MB; the limit is {max_bytes // MB} MB.")
        uploader = info.get("uploader")
        metadata = {
            "title": str(info.get("title") or video_id),
            "uploader": uploader if isinstance(uploader, str) else None,
            "duration": int(info["duration"]),
        }
        return json.dumps(metadata).encode()

    @classmethod
    def _options(
        cls,
        video_id: str,
        media_format: MediaFormat,
        max_height: int,
        max_bytes: int,
        ffmpeg: str,
        workdir: pathlib.Path,
    ) -> dict:
        options: dict = {
            # Named after the ID, so nothing from the page reaches a path.
            "outtmpl": {"default": f"{video_id}.%(ext)s"},
            "paths": {"home": str(workdir), "temp": str(workdir)},
            # Only the YouTube extractor: never the generic one, which would fetch whatever a page points to.
            "allowed_extractors": ["youtube"],
            "noplaylist": True,
            "cachedir": False,
            "ffmpeg_location": ffmpeg,
            "max_filesize": max_bytes,
            "socket_timeout": 30,
            "retries": 3,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        if media_format is MediaFormat.MP3:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(cls.MP3_BITRATE_KBPS)},
                {"key": "FFmpegMetadata"},
            ]
        else:
            options["format"] = "bv*+ba/b"
            # The best up to `max_height` on the shorter side (or the smallest above it), in H.264 and AAC if offered.
            options["format_sort"] = [f"res:{max_height}", "vcodec:h264", "acodec:aac"]
            options["merge_output_format"] = "mp4"
            options["postprocessors"] = [{"key": "FFmpegMetadata"}]
        return options

    @classmethod
    def _check(cls, info: dict, max_bytes: int) -> None:
        """Refuse what yt-dlp found before downloading any of it."""
        if info.get("_type", "video") != "video":
            raise ToolError(NOT_A_VIDEO)
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            raise ToolError("Live streams and premieres can't be downloaded; try again once it has ended.")
        duration = info.get("duration")
        if not isinstance(duration, int | float):
            raise ToolError("YouTube doesn't say how long this video is, so I won't download it.")
        if duration > cls.MAX_DURATION_SECONDS:
            raise ToolError(
                f"The video is {duration / 3600:.1f} hours long; the limit is {cls.MAX_DURATION_SECONDS // 3600} hours."
            )
        formats = info.get("requested_formats") or [info]
        estimate = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in formats)
        if estimate > max_bytes:
            raise ToolError(f"It would be about {estimate / MB:.0f} MB; the limit is {max_bytes // MB} MB.")

    @staticmethod
    def _youtube_error(message: str) -> str:
        """yt-dlp's error, without its colours, `ERROR:` and `[youtube] <id>:` prefixes."""
        message = re.sub(r"\x1b\[[0-9;]*m", "", message)
        message = re.sub(r"^ERROR:\s*", "", message)
        message = re.sub(r"^\[[\w:]+\]\s*(?:[\w-]+:\s*)?", "", message)
        return f"YouTube refused: {message.strip()[:300]}"
