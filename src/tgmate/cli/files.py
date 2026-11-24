"""Writing command output: existing files are only replaced with `--force`."""

import collections.abc as cabc
import pathlib
import shutil

import typer


def refuse_existing(paths: cabc.Iterable[pathlib.Path], *, force: bool, param_hint: str = "--output") -> None:
    """Check every output up front, so a command that writes several files writes none if one exists."""
    if force:
        return
    for path in paths:
        if path.exists():
            raise typer.BadParameter(f"{path} already exists; pass --force to overwrite it", param_hint=param_hint)


def write_output(path: pathlib.Path, data: bytes, *, force: bool, param_hint: str = "--output") -> None:
    try:
        with path.open("wb" if force else "xb") as file:
            file.write(data)
    except FileExistsError as exc:
        raise typer.BadParameter(f"{path} already exists; pass --force to overwrite it", param_hint=param_hint) from exc
    typer.echo(path)


def copy_output(source: pathlib.Path, path: pathlib.Path, *, force: bool, param_hint: str = "--output") -> None:
    """Like `write_output`, for a file too large to hold in memory (a downloaded video)."""
    try:
        with source.open("rb") as data, path.open("wb" if force else "xb") as file:
            shutil.copyfileobj(data, file)
    except FileExistsError as exc:
        raise typer.BadParameter(f"{path} already exists; pass --force to overwrite it", param_hint=param_hint) from exc
    typer.echo(path)
