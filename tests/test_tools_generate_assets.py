"""Unit tests for the branding and favicon asset generator tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from tools.generate_assets import (
    PNG_SPECS,
    AssetGenerationError,
    create_favicon_ico,
    generate_asset_suite,
    main,
    normalize_svg,
    parse_args,
    render_png,
    resolve_source_svg,
    update_social_preview,
)

SAMPLE_SVG_WITH_INCHES = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="11.937in" height="11.937in" viewBox="0 0 300 300" version="1.1" xmlns="http://www.w3.org/2000/svg">
    <circle cx="150" cy="150" r="100" fill="#592A8A"/>
</svg>
"""

SAMPLE_SVG_NO_DIMS = """<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
    <rect width="100" height="100" fill="#FFC72C"/>
</svg>
"""


def test_normalize_svg_replaces_physical_units() -> None:
    """Verify that physical dimensions are converted to responsive 100%."""
    normalized = normalize_svg(SAMPLE_SVG_WITH_INCHES)
    assert 'width="100%"' in normalized
    assert 'height="100%"' in normalized
    assert 'viewBox="0 0 300 300"' in normalized
    assert "11.937in" not in normalized


def test_normalize_svg_adds_missing_dimensions() -> None:
    """Verify that width and height are injected if not present."""
    normalized = normalize_svg(SAMPLE_SVG_NO_DIMS)
    assert 'width="100%"' in normalized
    assert 'height="100%"' in normalized
    assert 'viewBox="0 0 100 100"' in normalized


def test_create_favicon_ico(tmp_path: Path) -> None:
    """Verify multi-frame favicon.ico generation using Pillow."""
    source_png = tmp_path / "source_64.png"
    img = Image.new("RGBA", (64, 64), color=(89, 42, 138, 255))
    img.save(source_png, format="PNG")

    target_ico = tmp_path / "favicon.ico"
    create_favicon_ico(source_png, target_ico, sizes=[16, 32, 48, 64])

    assert target_ico.is_file()
    loaded_ico = Image.open(target_ico)
    assert loaded_ico.format == "ICO"


def test_render_png_inkscape(tmp_path: Path) -> None:
    """Verify rendering with Inkscape if installed."""
    svg_file = tmp_path / "test.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    out_png = tmp_path / "test_512.png"

    with (
        patch("shutil.which", return_value="/usr/bin/inkscape"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        render_png(svg_file, out_png, 512, 512)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "inkscape" in args[0]
        assert "--export-background-opacity=0" in args
        assert "--export-width=512" in args


def test_render_png_inkscape_failure(tmp_path: Path) -> None:
    """Verify AssetGenerationError is raised when inkscape fails."""
    svg_file = tmp_path / "test.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    out_png = tmp_path / "out.png"

    with (
        patch("shutil.which", return_value="/usr/bin/inkscape"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=1, stderr="Inkscape crash")
        with pytest.raises(AssetGenerationError, match="Inkscape failed rendering"):
            render_png(svg_file, out_png, 512, 512)


def test_render_png_magick_fallback(tmp_path: Path) -> None:
    """Verify ImageMagick fallback when inkscape is not available."""
    svg_file = tmp_path / "test.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    out_png = tmp_path / "out.png"

    def mock_which(cmd: str) -> str | None:
        return "/usr/bin/magick" if cmd == "magick" else None

    with (
        patch("shutil.which", side_effect=mock_which),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        render_png(svg_file, out_png, 180, 180)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "magick"
        assert "-resize" in args


def test_render_png_no_tool(tmp_path: Path) -> None:
    """Verify AssetGenerationError when neither inkscape nor magick is found."""
    svg_file = tmp_path / "test.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    out_png = tmp_path / "out.png"

    with (
        patch("shutil.which", return_value=None),
        pytest.raises(AssetGenerationError, match="Neither 'inkscape' nor 'magick'"),
    ):
        render_png(svg_file, out_png, 32, 32)


def test_generate_asset_suite_dry_run(tmp_path: Path) -> None:
    """Verify dry_run mode generates specs without touching target files."""
    svg_file = tmp_path / "source.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    target_dir = tmp_path / "target"

    def mock_render(_svg: Path, out: Path, w: int, h: int) -> None:
        Image.new("RGBA", (w, h)).save(out, format="PNG")

    with patch("tools.generate_assets.render_png", side_effect=mock_render):
        result = generate_asset_suite(
            svg_file,
            [target_dir],
            dry_run=True,
            verbose=False,
        )
        assert len(result["svg"]) == 2
        assert len(result["png"]) == len(PNG_SPECS)
        assert len(result["ico"]) == 1
        assert not target_dir.exists()


def test_generate_asset_suite_missing_file(tmp_path: Path) -> None:
    """Verify FileNotFoundError if source SVG does not exist."""
    missing = tmp_path / "missing_logo.svg"
    with pytest.raises(FileNotFoundError, match="Source SVG file not found"):
        generate_asset_suite(missing, [tmp_path / "target"])


def test_resolve_source_svg_explicit(tmp_path: Path) -> None:
    """Verify resolving explicit source path argument."""
    custom = tmp_path / "custom.svg"
    resolved = resolve_source_svg(custom)
    assert resolved == custom


def test_resolve_source_svg_not_found() -> None:
    """Verify FileNotFoundError when neither default file exists."""
    with (
        patch("pathlib.Path.is_file", return_value=False),
        pytest.raises(FileNotFoundError, match="Could not find source"),
    ):
        resolve_source_svg(None)


def test_parse_args_defaults() -> None:
    """Verify argument parser defaults."""
    args = parse_args([])
    assert args.source is None
    assert args.target_dirs is None
    assert not args.dry_run
    assert not args.no_social_preview
    assert not args.quiet


def test_update_social_preview_not_found(tmp_path: Path) -> None:
    """Verify update_social_preview returns False if preview file does not exist."""
    svg_file = tmp_path / "logo.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    missing_sp = tmp_path / "social-preview.png"
    assert not update_social_preview(svg_file, missing_sp)


def test_update_social_preview_dry_run(tmp_path: Path) -> None:
    """Verify update_social_preview returns True when dry_run is True."""
    svg_file = tmp_path / "logo.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    sp_file = tmp_path / "social-preview.png"
    Image.new("RGB", (1280, 640), (89, 42, 138)).save(sp_file, format="PNG")
    mtime_before = sp_file.stat().st_mtime

    result = update_social_preview(svg_file, sp_file, dry_run=True)
    assert result is True
    assert sp_file.stat().st_mtime == mtime_before


def test_update_social_preview_success(tmp_path: Path) -> None:
    """Verify update_social_preview successfully renders and composites logo."""
    svg_file = tmp_path / "logo.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    sp_file = tmp_path / "social-preview.png"
    Image.new("RGB", (1280, 640), (89, 42, 138)).save(sp_file, format="PNG")

    def mock_render(_svg: Path, out: Path, w: int, h: int) -> None:
        Image.new("RGBA", (w, h), (255, 255, 255, 255)).save(out, format="PNG")

    with patch("tools.generate_assets.render_png", side_effect=mock_render):
        result = update_social_preview(svg_file, sp_file, logo_size=200)

    assert result is True
    updated = Image.open(sp_file)
    assert updated.size == (1280, 640)


def test_main_happy_path(tmp_path: Path) -> None:
    """Verify main() entrypoint executes successfully with valid source."""
    svg_file = tmp_path / "ecu_hockey_logo.svg"
    svg_file.write_text(SAMPLE_SVG_WITH_INCHES, encoding="utf-8")
    target = tmp_path / "out"

    with (
        patch("tools.generate_assets.generate_asset_suite") as mock_gen,
        patch("tools.generate_assets.update_social_preview") as mock_sp,
    ):
        exit_code = main(
            [
                "--source",
                str(svg_file),
                "--target-dirs",
                str(target),
                "--quiet",
            ],
        )
        assert exit_code == 0
        mock_gen.assert_called_once()
        mock_sp.assert_called_once()


def test_main_error_handling(tmp_path: Path) -> None:
    """Verify main() handles exceptions cleanly with exit code 1."""
    missing_file = tmp_path / "nonexistent.svg"
    exit_code = main(["--source", str(missing_file)])
    assert exit_code == 1
