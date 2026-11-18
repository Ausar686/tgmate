import pytest
from typer.testing import CliRunner

from tests.images import decode_qr
from tests.terminal import plain
from tgmate.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def in_tmp_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_writes_qr_png_to_the_default_path(tmp_path):
    result = runner.invoke(app, ["qr", "example.com"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "qr.png"
    assert decode_qr((tmp_path / "qr.png").read_bytes()) == "https://example.com"


def test_output_suffix_picks_the_format(tmp_path):
    result = runner.invoke(app, ["qr", "https://example.com", "-o", "code.SVG"])

    assert result.exit_code == 0
    assert (tmp_path / "code.SVG").read_text().startswith("<?xml")


def test_unknown_output_suffix_is_a_usage_error(tmp_path):
    result = runner.invoke(app, ["qr", "https://example.com", "-o", "code.gif"])

    assert result.exit_code == 2
    assert ".png or .svg" in plain(result.stderr)
    assert not (tmp_path / "code.gif").exists()


def test_existing_output_is_kept_without_force(tmp_path):
    (tmp_path / "qr.png").write_bytes(b"keep me")

    result = runner.invoke(app, ["qr", "https://example.com"])

    assert result.exit_code == 2
    assert "--force" in plain(result.stderr)
    assert (tmp_path / "qr.png").read_bytes() == b"keep me"


def test_force_overwrites_existing_output(tmp_path):
    (tmp_path / "qr.png").write_bytes(b"old")

    result = runner.invoke(app, ["qr", "https://example.com", "--force"])

    assert result.exit_code == 0
    assert decode_qr((tmp_path / "qr.png").read_bytes()) == "https://example.com"


def test_invalid_address_reports_the_tool_error(tmp_path):
    result = runner.invoke(app, ["qr", "ftp://example.com"])

    assert result.exit_code == 1
    assert result.stderr == "Error: Only http and https web addresses are supported.\n"
    assert not (tmp_path / "qr.png").exists()


def test_unwritable_output_reports_the_os_error():
    result = runner.invoke(app, ["qr", "https://example.com", "-o", "missing-dir/qr.png"])

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert "No such file or directory" in result.stderr


def test_scale_outside_the_allowed_range_is_a_usage_error():
    result = runner.invoke(app, ["qr", "https://example.com", "--scale", "0"])

    assert result.exit_code == 2


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])

    assert "qr" in plain(result.output)
    assert "Usage" in plain(result.output)
