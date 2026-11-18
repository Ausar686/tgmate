"""`tgmate images-to-pdf` and `tgmate pdf-to-jpg`."""

import pathlib
import typing as t

import typer

from tgmate.cli.files import refuse_existing, write_output
from tgmate.tools.pdf import PDF, PageSize

Force = t.Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing output files.")]


def images_to_pdf(
    images: t.Annotated[
        list[pathlib.Path],
        typer.Argument(exists=True, dir_okay=False, help="Images, one page each, in this order."),
    ],
    output: t.Annotated[
        pathlib.Path | None,
        typer.Option("--output", "-o", dir_okay=False, help="PDF to write [default: the first image's name, .pdf]."),
    ] = None,
    page_size: t.Annotated[
        PageSize, typer.Option(case_sensitive=False, help="Paper to fit each image on, or the image's own size.")
    ] = PageSize.A4,
    force: Force = False,
) -> None:
    """Combine images (JPEG, PNG, WebP, GIF, BMP, TIFF) into one PDF."""
    target = output or pathlib.Path(images[0].stem + ".pdf")
    refuse_existing([target], force=force)
    pdf = PDF.from_images([path.read_bytes() for path in images], page_size)
    write_output(target, pdf, force=force)


def pdf_to_jpg(
    pdf: t.Annotated[pathlib.Path, typer.Argument(exists=True, dir_okay=False, help="PDF to convert.")],
    output_dir: t.Annotated[
        pathlib.Path,
        typer.Option("--output-dir", "-o", file_okay=False, help="Folder for the images; created if missing."),
    ] = pathlib.Path("."),
    dpi: t.Annotated[int, typer.Option(min=PDF.MIN_DPI, max=PDF.MAX_DPI, help="Resolution.")] = PDF.DEFAULT_DPI,
    force: Force = False,
) -> None:
    """Save each page of a PDF as a JPEG: <name>-1.jpg, <name>-2.jpg, … (zero-padded to sort in order)."""
    data = pdf.read_bytes()
    targets = [output_dir / name for name in PDF.jpeg_names(pdf.stem, PDF.page_count(data))]
    # Before rendering, which can take a while for a long PDF at a high DPI.
    refuse_existing(targets, force=force, param_hint="--output-dir")
    pages = PDF.to_jpegs(data, dpi)
    output_dir.mkdir(parents=True, exist_ok=True)
    for target, page in zip(targets, pages, strict=True):
        write_output(target, page, force=force, param_hint="--output-dir")
