"""Branding and favicon asset generator for ECU Hockey Calendar.

Reads a master SVG logo (e.g. ecu_hockey_logo.svg), normalizes its viewBox and
dimensions for responsive web and documentation display, rasterizes the full suite
of drop-in PNG resolutions (512x512, 192x192, 180x180, 32x32, 16x16), builds a
multi-frame Windows favicon.ico (16, 32, 48, 64), and distributes the complete
image set to all required repository directories:
    - static/
    - docs/_static/
    - src/ecu_hockey_calendar/api/static/
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageFilter

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_TARGET_DIRS: list[str] = [
    "static",
    "docs/_static",
    "src/ecu_hockey_calendar/api/static",
]

DEFAULT_SOCIAL_PREVIEW_PATH: Path = Path(".github/assets/social-preview.png")

PNG_SPECS: list[tuple[str, int, int]] = [
    ("ecu_hockey_logo.png", 512, 512),
    ("android-chrome-512x512.png", 512, 512),
    ("android-chrome-192x192.png", 192, 192),
    ("apple-touch-icon.png", 180, 180),
    ("favicon-32x32.png", 32, 32),
    ("favicon-16x16.png", 16, 16),
]

ICO_SIZES: tuple[int, ...] = (16, 32, 48, 64)


class AssetGenerationError(Exception):
    """Raised when asset generation or distribution fails."""


def normalize_svg(svg_content: str) -> str:
    """Normalize SVG header to ensure responsive scaling while preserving viewBox.

    Replaces fixed width/height physical dimensions (e.g. inches, mm, or fixed px)
    with 100% width and height so that the vector scales dynamically within any
    HTML or documentation container.

    Args:
        svg_content: Raw SVG file content as a string.

    Returns:
        Normalized SVG content with responsive width/height and preserved viewBox.
    """

    def _replace_svg_attrs(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r'\bwidth="[^"]*"', tag):
            tag = re.sub(r'\bwidth="[^"]*"', 'width="100%"', tag)
        else:
            tag = tag[:-1] + ' width="100%">'

        if re.search(r'\bheight="[^"]*"', tag):
            tag = re.sub(r'\bheight="[^"]*"', 'height="100%"', tag)
        else:
            tag = tag[:-1] + ' height="100%">'

        return tag

    return re.sub(r"<svg\b[^>]*>", _replace_svg_attrs, svg_content, count=1)


def render_png(svg_path: Path, output_path: Path, width: int, height: int) -> None:
    """Rasterize an SVG to PNG at specific dimensions using available system tools.

    Prefers inkscape, falling back to ImageMagick if inkscape is not present.

    Args:
        svg_path: Path to input SVG file.
        output_path: Path to write rendered PNG.
        width: Pixel width.
        height: Pixel height.

    Raises:
        AssetGenerationError: If no rendering tool is found or rendering fails.
    """
    if shutil.which("inkscape"):
        cmd = [
            "inkscape",
            "--export-type=png",
            "--export-background-opacity=0",
            f"--export-width={width}",
            f"--export-height={height}",
            f"--export-filename={output_path}",
            str(svg_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            msg = (
                f"Inkscape failed rendering {svg_path} to {output_path}: "
                f"{result.stderr.strip()}"
            )
            raise AssetGenerationError(msg)

        return

    if shutil.which("magick"):
        cmd = [
            "magick",
            "-background",
            "none",
            "-density",
            "300",
            str(svg_path),
            "-resize",
            f"{width}x{height}",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            msg = (
                f"ImageMagick failed rendering {svg_path} to {output_path}: "
                f"{result.stderr.strip()}"
            )
            raise AssetGenerationError(msg)

        return

    msg = (
        "Neither 'inkscape' nor 'magick' command is installed. "
        "Please install Inkscape or ImageMagick to render SVG to PNG."
    )
    raise AssetGenerationError(msg)


def create_favicon_ico(
    source_png: Path,
    output_path: Path,
    sizes: Sequence[int] = ICO_SIZES,
) -> None:
    """Build a multi-frame Windows icon (ICO) file containing standard resolutions.

    Args:
        source_png: Path to high-resolution (>=64px) source PNG.
        output_path: Target path for the generated .ico file.
        sizes: Pixel dimensions to include as icon frames.
    """
    img = Image.open(source_png)
    ico_sizes = [(s, s) for s in sizes]
    img.save(output_path, format="ICO", sizes=ico_sizes)


def _render_all_pngs(
    temp_svg: Path,
    temp_dir_path: Path,
    *,
    verbose: bool,
) -> dict[str, Path]:
    """Render all PNG specs from a normalized SVG file."""
    rendered_pngs: dict[str, Path] = {}
    for filename, w, h in PNG_SPECS:
        dest_temp_png = temp_dir_path / filename
        if verbose:
            print(f"  Rendering {filename} ({w}x{h})...")

        render_png(temp_svg, dest_temp_png, w, h)
        rendered_pngs[filename] = dest_temp_png

    return rendered_pngs


def _copy_asset(
    source_path: Path,
    target_path: Path,
    *,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Copy a file to target path unless in dry_run mode."""
    if not dry_run:
        shutil.copyfile(source_path, target_path)

    if verbose:
        print(f"  -> {target_path}")


def _distribute_to_directory(
    target_dir: Path,
    normalized_content: str,
    rendered_pngs: dict[str, Path],
    temp_ico: Path,
    *,
    dry_run: bool,
    verbose: bool,
    created_files: dict[str, list[Path]],
) -> None:
    """Copy rendered assets into a specific target directory."""
    if verbose:
        print(f"Distributing assets to: {target_dir}")

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for svg_name in ["ecu_hockey_logo.svg", "favicon.svg"]:
        target_path = target_dir / svg_name
        if not dry_run:
            target_path.write_text(normalized_content, encoding="utf-8")

        created_files["svg"].append(target_path)
        if verbose:
            print(f"  -> {target_path}")

    for filename, _, _ in PNG_SPECS:
        target_path = target_dir / filename
        _copy_asset(
            rendered_pngs[filename],
            target_path,
            dry_run=dry_run,
            verbose=verbose,
        )
        created_files["png"].append(target_path)

    target_ico = target_dir / "favicon.ico"
    _copy_asset(temp_ico, target_ico, dry_run=dry_run, verbose=verbose)
    created_files["ico"].append(target_ico)


def generate_asset_suite(
    source_svg: Path,
    target_dirs: Sequence[Path],
    *,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, list[Path]]:
    """Generate all brand asset formats and distribute them to target directories.

    Args:
        source_svg: Path to the source master SVG logo.
        target_dirs: Sequence of directories to receive the asset suite.
        dry_run: If True, validate steps without writing files.
        verbose: If True, print progress messages.

    Returns:
        Mapping of asset type to list of generated file paths.

    Raises:
        FileNotFoundError: If the source SVG does not exist.
    """
    if not source_svg.is_file():
        msg = f"Source SVG file not found: {source_svg}"
        raise FileNotFoundError(msg)

    raw_content = source_svg.read_text(encoding="utf-8")
    normalized_content = normalize_svg(raw_content)

    created_files: dict[str, list[Path]] = {
        "svg": [],
        "png": [],
        "ico": [],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_svg = temp_dir_path / "normalized.svg"
        temp_svg.write_text(normalized_content, encoding="utf-8")

        rendered_pngs = _render_all_pngs(temp_svg, temp_dir_path, verbose=verbose)

        ico_master_png = temp_dir_path / "ico_master_64.png"
        render_png(temp_svg, ico_master_png, 64, 64)
        temp_ico = temp_dir_path / "favicon.ico"
        create_favicon_ico(ico_master_png, temp_ico, sizes=ICO_SIZES)

        for target_dir in target_dirs:
            _distribute_to_directory(
                target_dir,
                normalized_content,
                rendered_pngs,
                temp_ico,
                dry_run=dry_run,
                verbose=verbose,
                created_files=created_files,
            )

    return created_files


_SP_TOP_BAR_HEIGHT: int = 8
_SP_BOTTOM_BAR_Y: int = 632
_SP_BOTTOM_LINE_Y: int = 624
_SP_GRID_INTERVAL: int = 48


def _generate_social_preview_left_bg(
    width: int = 528,
    height: int = 640,
) -> Image.Image:
    """Construct hockey rink grid background with ECU purple and gold borders."""
    left_bg = Image.new("RGBA", (width, height), (89, 42, 138, 255))
    pixels = left_bg.load()
    if pixels is None:
        msg = "Failed to load pixel access for social preview background"
        raise AssetGenerationError(msg)

    for x in range(width):
        for y in range(height):
            if y <= _SP_TOP_BAR_HEIGHT or y >= _SP_BOTTOM_BAR_Y:
                pixels[x, y] = (255, 199, 44, 255)
            elif (
                y == _SP_BOTTOM_LINE_Y
                or x % _SP_GRID_INTERVAL == 0
                or y % _SP_GRID_INTERVAL == 0
            ):
                pixels[x, y] = (255, 255, 255, 255)

    return left_bg


def _apply_logo_with_shadow(
    background: Image.Image,
    logo: Image.Image,
    center_pos: tuple[int, int] = (270, 320),
) -> None:
    """Composite logo with a soft drop shadow onto the background panel."""
    cx, cy = center_pos
    w, h = logo.size
    lx = cx - w // 2
    ly = cy - h // 2
    pad = 50
    shadow_mask = Image.new("L", (w + pad * 2, h + pad * 2), 0)
    shadow_mask.paste(logo.split()[3], (pad, pad + 6))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(10))
    black = Image.new("RGBA", shadow_mask.size, (0, 0, 0, 160))
    background.paste(black, (lx - pad, ly - pad), mask=shadow_mask)
    background.paste(logo, (lx, ly), mask=logo.split()[3])


def update_social_preview(
    source_svg: Path,
    social_preview_path: Path = DEFAULT_SOCIAL_PREVIEW_PATH,
    *,
    logo_size: int = 400,
    dry_run: bool = False,
    verbose: bool = True,
) -> bool:
    """Update Open Graph social preview card with the new brand logo.

    Reconstructs the left panel hockey rink grid background with brand purple,
    accent borders, and white grid lines, pastes the resized logo with a subtle
    realistic drop shadow, and saves the updated preview.

    Args:
        source_svg: Path to source SVG logo.
        social_preview_path: Path to social-preview.png file.
        logo_size: Width and height of the embedded logo in pixels.
        dry_run: If True, do not write changes to disk.
        verbose: If True, print progress messages.

    Returns:
        True if the social preview card was updated, False if skipped.
    """
    if not social_preview_path.is_file():
        return False

    if verbose:
        print(f"Updating social preview card: {social_preview_path}")

    if dry_run:
        return True

    sp = Image.open(social_preview_path).convert("RGBA")
    panel_width, panel_height = 528, 640

    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_png = Path(temp_dir) / "logo_hires.png"
        render_png(source_svg, tmp_png, 1024, 1024)
        logo_hires = Image.open(tmp_png)
        logo = logo_hires.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

    left_bg = _generate_social_preview_left_bg(panel_width, panel_height)
    _apply_logo_with_shadow(left_bg, logo, (270, 320))

    sp.paste(left_bg, (0, 0))
    sp.convert("RGB").save(social_preview_path, format="PNG")
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the asset generator tool."""
    parser = argparse.ArgumentParser(
        description="Generate and distribute responsive SVG, PNG, and ICO assets.",
    )
    parser.add_argument(
        "--source",
        "-s",
        type=Path,
        default=None,
        help="Path to source SVG logo (default: ./ecu_hockey_logo.svg)",
    )
    parser.add_argument(
        "--target-dirs",
        "-t",
        nargs="+",
        type=Path,
        default=None,
        help=f"Target directories to receive assets (default: {DEFAULT_TARGET_DIRS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render in temp directory without writing destination files",
    )
    parser.add_argument(
        "--no-social-preview",
        action="store_true",
        help="Skip updating .github/assets/social-preview.png",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress output messages",
    )
    return parser.parse_args(argv)


def resolve_source_svg(source_arg: Path | None) -> Path:
    """Resolve the source SVG path from arguments or default locations."""
    if source_arg is not None:
        return source_arg

    if Path("ecu_hockey_logo.svg").is_file():
        return Path("ecu_hockey_logo.svg")

    if Path("static/ecu_hockey_logo.svg").is_file():
        return Path("static/ecu_hockey_logo.svg")

    msg = "Could not find source ecu_hockey_logo.svg in root or static/ directory."
    raise FileNotFoundError(msg)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for asset generator."""
    args = parse_args(argv)

    try:
        source_svg = resolve_source_svg(args.source)
        target_dirs = (
            [Path(d) for d in args.target_dirs]
            if args.target_dirs
            else [Path(d) for d in DEFAULT_TARGET_DIRS]
        )

        if not args.quiet:
            print(f"Source SVG: {source_svg}")
            print(f"Target directories: {[str(d) for d in target_dirs]}")

        generate_asset_suite(
            source_svg,
            target_dirs,
            dry_run=args.dry_run,
            verbose=not args.quiet,
        )

        if not args.no_social_preview:
            update_social_preview(
                source_svg,
                dry_run=args.dry_run,
                verbose=not args.quiet,
            )
    except (FileNotFoundError, AssetGenerationError, OSError) as exc:
        print(f"Error generating assets: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print("Successfully generated and distributed all brand assets.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
