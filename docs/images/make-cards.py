"""Turn the four client screenshots into the README's matching square cards.

    python3 docs/images/make-cards.py      # needs Pillow (pip install pillow)

The screenshots have nothing in common — a wide console, a window, a tall
phone, a small watch — and side by side in the README's 2x2 table they sat at
four different heights. Each goes on the same square, as a window or inside
a device bezel, scaled to fit and never cropped. Rerun after replacing a
screenshot; the cards are what the README shows.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SIZE = 1000
SUPERSAMPLE = 4
TOP, BOTTOM = (246, 245, 255), (229, 227, 247)
SHADOW = (32, 28, 72)
BEZEL = (20, 20, 24)


def rounded_mask(width, height, radius):
    """An anti-aliased rounded rectangle, drawn large and scaled down."""
    big = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        [0, 0, width * SUPERSAMPLE - 1, height * SUPERSAMPLE - 1],
        radius=radius * SUPERSAMPLE, fill=255,
    )
    return big.resize((width, height), Image.LANCZOS)


def blank_card():
    gradient = Image.linear_gradient("L").resize((SIZE, SIZE))
    card = Image.composite(Image.new("RGB", (SIZE, SIZE), BOTTOM),
                           Image.new("RGB", (SIZE, SIZE), TOP), gradient)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(card, (0, 0), rounded_mask(SIZE, SIZE, 48))
    return out


def drop_shadow(card, x, y, width, height, radius):
    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [x, y + 14, x + width, y + height + 14], radius=radius, fill=(*SHADOW, 70)
    )
    card.alpha_composite(layer.filter(ImageFilter.GaussianBlur(26)))


def paste_rounded(card, image, x, y, width, height, radius):
    image = image.convert("RGBA").resize((width, height), Image.LANCZOS)
    card.paste(image, (x, y), rounded_mask(width, height, radius))


def window_card(source, margin=40, radius=14):
    """A desktop or browser screenshot, as wide as the card allows."""
    shot = Image.open(source)
    width = SIZE - 2 * margin
    height = round(width * shot.height / shot.width)
    x, y = margin, (SIZE - height) // 2
    card = blank_card()
    drop_shadow(card, x, y, width, height, radius)
    paste_rounded(card, shot, x, y, width, height, radius)
    return card


def device_card(source, screen_height, bezel, screen_radius, bezel_radius):
    """A phone or watch screenshot inside a dark bezel."""
    shot = Image.open(source)
    width = round(screen_height * shot.width / shot.height)
    outer_w, outer_h = width + 2 * bezel, screen_height + 2 * bezel
    x, y = (SIZE - outer_w) // 2, (SIZE - outer_h) // 2
    card = blank_card()
    drop_shadow(card, x, y, outer_w, outer_h, bezel_radius)
    frame = Image.new("RGBA", (outer_w, outer_h), (*BEZEL, 255))
    card.paste(frame, (x, y), rounded_mask(outer_w, outer_h, bezel_radius))
    paste_rounded(card, shot, x + bezel, y + bezel, width, screen_height, screen_radius)
    return card


CARDS = {
    "card-web.png": lambda: window_card(HERE / "parallel-tasks.png"),
    "card-desktop.png": lambda: window_card(HERE / "client-desktop.png"),
    "card-phone.png": lambda: device_card(HERE / "client-phone.png", 780, 12, 48, 58),
    "card-watch.png": lambda: device_card(HERE / "client-watch.png", 580, 22, 88, 110),
}

if __name__ == "__main__":
    for name, make in CARDS.items():
        make().save(HERE / name, optimize=True)
        print(f"wrote {name}")
