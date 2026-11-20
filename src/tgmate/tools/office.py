"""Office documents (Word, OpenDocument text, RTF) to PDF, converted by LibreOffice in the sandbox."""

import enum
import io
import pathlib
import shutil
import subprocess  # nosec B404
import tempfile
import zipfile

from tgmate.tools import sandbox
from tgmate.tools.errors import ToolError


class DocumentFormat(enum.StrEnum):
    """Supported formats, by file extension."""

    DOCX = "docx"
    DOC = "doc"
    ODT = "odt"
    RTF = "rtf"


# LibreOffice's import filter for each format: it opens the file only as that format, never as whatever else
# LibreOffice could make of it (a spreadsheet, a presentation, a web page).
IMPORT_FILTERS = {
    DocumentFormat.DOCX: "MS Word 2007 XML",
    DocumentFormat.DOC: "MS Word 97",
    DocumentFormat.ODT: "writer8",
    DocumentFormat.RTF: "Rich Text Format",
}
OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ODT_MIMETYPE = b"application/vnd.oasis.opendocument.text"
UNSUPPORTED = "This isn't a Word (DOCX or DOC), OpenDocument text (ODT) or RTF document."
# Where the macOS app keeps it; elsewhere `soffice` is on PATH.
MACOS_SOFFICE = pathlib.Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")

# Settings for each job's fresh LibreOffice profile. By default LibreOffice fetches images a document links to on the
# web and embeds linked local files, so a document could make the bot request any URL or copy any image it can read
# into the PDF. Blocking untrusted links stops both; the dead proxy and disabled macros and active content are a
# second line.
_SETTINGS = {
    "/org.openoffice.Office.Common/Security/Scripting": {
        "BlockUntrustedRefererLinks": "true",
        "DisableActiveContent": "true",
        "DisableMacrosExecution": "true",
        "MacroSecurityLevel": "3",
    },
    "/org.openoffice.Inet/Settings": {
        "ooInetProxyType": "1",
        "ooInetNoProxy": "",
        **{f"ooInet{scheme}ProxyName": "127.0.0.1" for scheme in ("HTTP", "HTTPS", "FTP")},
        **{f"ooInet{scheme}ProxyPort": "9" for scheme in ("HTTP", "HTTPS", "FTP")},
    },
}
PROFILE_SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    + "".join(
        f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse"><value>{value}</value></prop></item>\n'
        for path, props in _SETTINGS.items()
        for name, value in props.items()
    )
    + "</oor:items>\n"
)


class Office:
    """Converts office documents to PDF with LibreOffice."""

    # DOCX and ODT are ZIP archives; checked before LibreOffice unpacks them.
    MAX_ARCHIVE_ENTRIES = 10_000
    MAX_UNPACKED_BYTES = 512 * 1024 * 1024

    @classmethod
    def to_pdf(cls, data: bytes) -> bytes:
        """Return the document (DOCX, DOC, ODT or RTF) as a PDF."""
        soffice = cls.soffice()
        with tempfile.TemporaryDirectory(prefix="tgmate-") as workdir:
            [pdf] = sandbox.run(
                "office.to_pdf", [data], {"soffice": soffice}, outputs=range(1, 2), workdir=pathlib.Path(workdir)
            )
        return pdf

    @staticmethod
    def soffice() -> str:
        """The LibreOffice executable; refuses with `ToolError` when it isn't installed."""
        found = shutil.which("soffice") or (str(MACOS_SOFFICE) if MACOS_SOFFICE.exists() else None)
        if found is None:
            raise ToolError("LibreOffice isn't installed here, so I can't convert documents.")
        return found

    # The operation itself, run by the sandbox's worker.

    @classmethod
    def _to_pdf(cls, data: bytes, soffice: str, workdir: pathlib.Path) -> bytes:
        document_format = cls._detect(data)
        # Fixed names: nothing from the user reaches LibreOffice's command line.
        source = workdir / f"document.{document_format}"
        source.write_bytes(data)
        profile = workdir / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(PROFILE_SETTINGS)
        output = workdir / "output"
        subprocess.run(  # nosec B603
            [
                soffice,
                f"-env:UserInstallation={profile.as_uri()}",
                "--headless",
                "--nolockcheck",
                "--nologo",
                "--nodefault",
                "--norestore",
                f"--infilter={IMPORT_FILTERS[document_format]}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(output),
                str(source),
            ],
            # The job's directory as home, so LibreOffice keeps nothing between jobs; the worker's own environment is
            # already empty.
            env={"HOME": str(workdir), "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            check=False,
        )
        pdf = output / "document.pdf"
        if not pdf.exists():
            raise ToolError(f"LibreOffice couldn't open this {document_format.upper()} document; it may be damaged.")
        return pdf.read_bytes()

    @classmethod
    def _detect(cls, data: bytes) -> DocumentFormat:
        """The document's format from its content, whatever its name says."""
        if data.startswith(OLE2_SIGNATURE):
            return DocumentFormat.DOC
        if data.startswith(b"{\\rtf"):
            return DocumentFormat.RTF
        if data.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    return cls._detect_archive(archive)
            except zipfile.BadZipFile:
                pass
        raise ToolError(UNSUPPORTED)

    @classmethod
    def _detect_archive(cls, archive: zipfile.ZipFile) -> DocumentFormat:
        entries = archive.infolist()
        if len(entries) > cls.MAX_ARCHIVE_ENTRIES:
            raise ToolError(f"The document has more than {cls.MAX_ARCHIVE_ENTRIES} parts.")
        if sum(entry.file_size for entry in entries) > cls.MAX_UNPACKED_BYTES:
            raise ToolError(f"The document unpacks to more than {cls.MAX_UNPACKED_BYTES // (1024 * 1024)} MB.")
        names = {entry.filename: entry for entry in entries}
        if "word/document.xml" in names:
            return DocumentFormat.DOCX
        mimetype = names.get("mimetype")
        if mimetype is not None and mimetype.file_size == len(ODT_MIMETYPE) and archive.read(mimetype) == ODT_MIMETYPE:
            return DocumentFormat.ODT
        raise ToolError(UNSUPPORTED)
