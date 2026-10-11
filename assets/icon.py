"""
assets/icon.py - Embedded icon generator and base64 store for MC Download Manager.
Provides an application icon in PIL Image, Tk PhotoImage, and raw bytes format.
"""
import base64
import io
from PIL import Image, ImageDraw


def create_default_icon_image(size: int = 64) -> Image.Image:
    """Draw a modern, stylized download arrow icon with a circular badge."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle (gradient-like or deep blue/cyan accent)
    bg_color = (30, 144, 255, 255)  # Dodger Blue
    draw.ellipse([2, 2, size - 3, size - 3], fill=bg_color)

    # Arrow coordinates scaled to size
    arrow_color = (255, 255, 255, 255)
    
    # Arrow stem
    stem_w = max(4, size // 8)
    stem_left = (size - stem_w) // 2
    stem_right = stem_left + stem_w
    stem_top = size // 4
    stem_bottom = int(size * 0.58)
    draw.rectangle([stem_left, stem_top, stem_right, stem_bottom], fill=arrow_color)

    # Arrow head (triangle)
    head_left = size // 4
    head_right = size - head_left
    head_peak_y = int(size * 0.72)
    draw.polygon(
        [
            (head_left, stem_bottom),
            (head_right, stem_bottom),
            (size // 2, head_peak_y),
        ],
        fill=arrow_color,
    )

    # Tray bar / bottom platform
    bar_y1 = int(size * 0.78)
    bar_y2 = int(size * 0.85)
    bar_x1 = size // 4
    bar_x2 = size - bar_x1
    draw.rectangle([bar_x1, bar_y1, bar_x2, bar_y2], fill=arrow_color)

    return img


def get_icon_bytes(size: int = 64) -> bytes:
    """Return PNG bytes of the generated icon."""
    img = create_default_icon_image(size)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def get_icon_base64(size: int = 64) -> str:
    """Return base64 encoded string of PNG icon."""
    return base64.b64encode(get_icon_bytes(size)).decode("utf-8")


# Pre-generated icon in base64
APP_ICON_B64 = get_icon_base64(64)


def get_app_icon_image() -> Image.Image:
    """Return PIL Image instance from base64 icon."""
    raw = base64.b64decode(APP_ICON_B64.encode("utf-8"))
    return Image.open(io.BytesIO(raw))
