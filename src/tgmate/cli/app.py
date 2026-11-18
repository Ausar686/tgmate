"""The `tgmate` command line: one subcommand per tool."""

import functools
import typing as t

import typer

from tgmate.cli import pdf, qr
from tgmate.tools.errors import ToolError

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_show_locals=False)


@app.callback()
def tgmate() -> None:
    """Everyday tools: QR codes, images to PDF and PDF to JPG."""


def reports_errors[**P](command: t.Callable[P, None]) -> t.Callable[P, None]:
    """Turn input and file errors into a one-line message and exit code 1 instead of a traceback."""

    @functools.wraps(command)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            command(*args, **kwargs)
        except (ToolError, OSError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc

    return wrapper


app.command()(reports_errors(qr.qr))
app.command()(reports_errors(pdf.images_to_pdf))
app.command()(reports_errors(pdf.pdf_to_jpg))
