"""Draw the home-screen icons (PWA): a white cross on the site's accent green.

    python scripts/make_icons.py      writes human_scoring/icons/*.png

icon-*.png have rounded corners on a transparent background; maskable-*.png fill the whole
square (Android crops them to its own shape), with the cross inside the central safe zone.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "human_scoring" / "icons"
GREEN = (74, 103, 65, 255)   # --accent in human-scoring.html
WHITE = (255, 255, 255, 255)


def _cross(d: ImageDraw.ImageDraw, size: int, scale: float) -> None:
    """A Latin cross centred in the square, `scale` of its height."""
    h = size * scale
    w = h * 0.12                         # beam thickness
    cx, top = size / 2, (size - h) / 2
    d.rectangle([cx - w / 2, top, cx + w / 2, top + h], fill=WHITE)
    arm, y = h * 0.62, top + h * 0.30
    d.rectangle([cx - arm / 2, y - w / 2, cx + arm / 2, y + w / 2], fill=WHITE)


def icon(size: int, maskable: bool) -> Image.Image:
    big = size * 4  # draw large, then shrink: smooth edges
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if maskable:
        d.rectangle([0, 0, big, big], fill=GREEN)
        _cross(d, big, 0.50)  # inside the 80% safe circle
    else:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 0.22, fill=GREEN)
        _cross(d, big, 0.62)
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        icon(size, False).save(OUT / f"icon-{size}.png", optimize=True)
        icon(size, True).save(OUT / f"maskable-{size}.png", optimize=True)
    # iOS draws its own rounded corners and shows black behind transparency: a full square
    icon(180, True).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    print("寫出", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
