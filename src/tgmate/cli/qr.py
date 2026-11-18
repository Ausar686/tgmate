"""`tgmate qr`: save a QR code for a web address."""

import pathlib
import typing as t

import typer

from tgmate.cli.files import write_output
from tgmate.tools.qr import ImageFormat, QRCode


def qr(
    url: t.Annotated[str, typer.Argument(help="Web address to encode; https:// is assumed without a scheme.")],
    output: t.Annotated[
        pathlib.Path, typer.Option("--output", "-o", dir_okay=False, help="Image to write: .png or .svg.")
    ] = pathlib.Path("qr.png"),
    scale: t.Annotated[
        int, typer.Option(min=1, max=QRCode.MAX_SCALE, help="Pixels per QR module (PNG) or SVG units.")
    ] = QRCode.DEFAULT_SCALE,
    force: t.Annotated[bool, typer.Option("--force", "-f", help="Overwrite the output file.")] = False,
) -> None:
    """Save a QR code that opens a web address."""
    try:
        fmt = ImageFormat(output.suffix.lower().removeprefix("."))
    except ValueError as exc:
        raise typer.BadParameter("must end in .png or .svg", param_hint="--output") from exc
    write_output(output, QRCode.from_url(url, fmt, scale), force=force)
