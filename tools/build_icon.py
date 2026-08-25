from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "event_checklist" / "resources" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def font(size: int):
    candidates = [
        Path(r"C:\Windows\Fonts\malgunbd.ttf"),
        Path(r"C:\Windows\Fonts\malgun.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), max(8, int(size * 0.31)))
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    margin = max(1, int(size * 0.03)) * scale
    radius = int(size * 0.23) * scale
    draw.rounded_rectangle(
        (margin, margin, size * scale - margin, size * scale - margin),
        radius=radius,
        fill=(242, 91, 36, 255),
    )
    label = "이플" if size >= 24 else "이"
    selected_font = font(size * scale)
    box = draw.textbbox((0, 0), label, font=selected_font)
    width, height = box[2] - box[0], box[3] - box[1]
    draw.text(
        ((size * scale - width) / 2, (size * scale - height) / 2 - box[1] - size * scale * 0.02),
        label,
        font=selected_font,
        fill="white",
    )
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    images = [render(size) for size in SIZES]
    images[-1].save(OUT / "event_flow_icon.png")
    images[-1].save(OUT / "event_flow.ico", format="ICO", sizes=[(size, size) for size in SIZES])


if __name__ == "__main__":
    main()
