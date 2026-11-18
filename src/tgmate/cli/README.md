# cli

The `tgmate` command (Typer). [app.py](app.py) holds the app and registers one
subcommand per tool; each command lives in its own module and only parses
arguments, calls the tool and writes the result.

## Commands
| Command | Does | Module |
| --- | --- | --- |
| `tgmate qr URL [-o qr.png] [--scale N] [-f]` | Writes a QR code for `URL`; the output's suffix (`.png` / `.svg`) picks the format | [qr.py](qr.py) |
| `tgmate images-to-pdf IMAGE... [-o NAME.pdf] [--page-size a4\|letter\|image] [-f]` | Combines images into one PDF, one page each; named after the first image by default | [pdf.py](pdf.py) |
| `tgmate pdf-to-jpg PDF [-o DIR] [--dpi 150] [-f]` | Writes each page as `DIR/<name>-<n>.jpg`, numbers zero-padded to sort in order | [pdf.py](pdf.py) |
| `tgmate doc-to-pdf DOCUMENT [-o NAME.pdf] [-f]` | Converts a DOCX, DOC, ODT or RTF document to PDF with LibreOffice (which must be installed); named after the document, in the current folder, by default | [office.py](office.py) |

`tgmate --help` and `tgmate <command> --help` list every option.

## Conventions
- Output files are never overwritten unless `--force` is given; a command
  that writes several files checks them all first and writes none if one
  exists ([files.py](files.py)).
- Successful commands print the path they wrote to stdout.
- Exit codes: `0` success; `1` the tool refused the input (`ToolError`) or a
  file couldn't be read or written, shown as one `Error: …` line on stderr;
  `2` bad usage (unknown option, value out of range, existing output), shown
  by Typer.
- Register a new command with `reports_errors` (see `app.py`) so its errors
  follow the same format.
