"""Writing command output: existing files are only replaced with `--force`."""

import collections.abc as cabc
import pathlib

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
