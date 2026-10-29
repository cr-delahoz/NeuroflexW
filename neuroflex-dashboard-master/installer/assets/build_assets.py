"""
Genera los assets graficos (BMP e ICO) para el instalador NSIS con MUI2.

Uso:
    python installer/assets/build_assets.py

Genera:
    installer/assets/welcome.bmp      164x314  panel lateral welcome/finish (installer)
    installer/assets/un-welcome.bmp   164x314  panel lateral welcome/finish (uninstaller)
    installer/assets/header.bmp       150x57   franja superior paginas internas
    installer/assets/neuroflex.ico     multi   icono del EXE (256/48/32/16)

Gradiente lineal vertical:
    0%   -> #3D77BA
    50%  -> #213067
    100% -> #03030B
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent
LOGO_PATH = ASSETS_DIR.parent / "NFVR_logo.png"

# Colores del gradiente (RBG)
GRAD_TOP = (0x3D, 0x77, 0xBA)
GRAD_MID = (0x21, 0x30, 0x67)
GRAD_BOT = (0x03, 0x03, 0x0B)

# Texto
WHITE = (0xFF, 0xFF, 0xFF)
WHITE_85 = (0xFF, 0xFF, 0xFF, 0xD9)
WHITE_70 = (0xFF, 0xFF, 0xFF, 0xB3)

# Dimensiones NSIS MUI2 (exactas, no cambiar)
WELCOME_W, WELCOME_H = 164, 314
UN_WELCOME_W, UN_WELCOME_H = 164, 314
HEADER_W, HEADER_H = 150, 57

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lerp_color(c1, c2, t):
    """Interpola linealmente entre dos colores RGB."""
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def vertical_gradient(width, height, top, mid, bottom):
    """
    Gradiente vertical lineal a 3 puntos.
    0%   -> top
    50%  -> mid
    100% -> bottom
    """
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    half = height / 2
    for y in range(height):
        if y < half:
            t = y / half
            color = lerp_color(top, mid, t)
        else:
            t = (y - half) / (height - half) if height > half else 1.0
            color = lerp_color(mid, bottom, t)
        for x in range(width):
            pixels[x, y] = color
    return img


def horizontal_gradient(width, height, top, mid, bottom):
    """Igual que vertical_gradient pero horizontal."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    half = width / 2
    for x in range(width):
        if x < half:
            t = x / half
            color = lerp_color(top, mid, t)
        else:
            t = (x - half) / (width - half) if width > half else 1.0
            color = lerp_color(mid, bottom, t)
        for y in range(height):
            pixels[x, y] = color
    return img


def load_font(size, bold=True):
    """Carga Arial Bold (fallback a default)."""
    candidates = ["arialbd.ttf", "arial.ttf"]
    if bold:
        candidates = ["arialbd.ttf", "ariblk.ttf", "arial.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def paste_logo(base_img, max_width_ratio=0.72, max_height_ratio=0.28,
               y_offset_ratio=0.06):
    """
    Pega el logo PNG (con alpha) centrado horizontalmente sobre base_img.
    Mantiene proporcion y limita tamaño.
    """
    if not LOGO_PATH.exists():
        sys.stderr.write(
            f"[warn] Logo no encontrado en {LOGO_PATH} — se omite el logo.\n"
        )
        return base_img

    logo = Image.open(LOGO_PATH).convert("RGBA")
    bw, bh = base_img.size
    max_w = int(bw * max_width_ratio)
    max_h = int(bh * max_height_ratio)

    # Escalar manteniendo proporcion
    ratio = min(max_w / logo.width, max_h / logo.height)
    new_w = max(1, int(logo.width * ratio))
    new_h = max(1, int(logo.height * ratio))
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # Pegar centrado horizontalmente, cerca de la parte superior
    px = (bw - new_w) // 2
    py = int(bh * y_offset_ratio)
    base_img.paste(logo, (px, py), logo)
    return base_img


def draw_centered_text(img, text, font, y, fill=WHITE):
    """Dibuja texto centrado horizontalmente en y."""
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (img.width - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return img


def save_bmp(img, path, bits=24):
    """Guarda como BMP. NSIS MUI2 requiere BMP (24-bit o 32-bit)."""
    img.save(str(path), "BMP", bits=bits)
    print(f"  [ok] {path.name}  ({img.width}x{img.height}  {bits}-bit BMP)")


# ---------------------------------------------------------------------------
# Generadores
# ---------------------------------------------------------------------------

def build_welcome():
    """Panel lateral welcome/finish del installer."""
    img = vertical_gradient(WELCOME_W, WELCOME_H, GRAD_TOP, GRAD_MID, GRAD_BOT)
    img = paste_logo(img, y_offset_ratio=0.07)

    font_title = load_font(15, bold=True)
    font_sub = load_font(10, bold=False)

    draw_centered_text(img, "NeuroFlex", font_title, int(WELCOME_H * 0.60), WHITE)
    draw_centered_text(img, "Dashboard VR", font_sub, int(WELCOME_H * 0.68), WHITE_85)

    save_bmp(img, ASSETS_DIR / "welcome.bmp")


def build_un_welcome():
    """Panel lateral welcome/finish del uninstaller."""
    img = vertical_gradient(UN_WELCOME_W, UN_WELCOME_H, GRAD_TOP, GRAD_MID, GRAD_BOT)
    img = paste_logo(img, y_offset_ratio=0.07)

    font_title = load_font(15, bold=True)
    font_sub = load_font(10, bold=False)

    draw_centered_text(img, "NeuroFlex", font_title, int(UN_WELCOME_H * 0.58), WHITE)
    draw_centered_text(img, "Desinstalacion", font_sub, int(UN_WELCOME_H * 0.66), WHITE_85)

    save_bmp(img, ASSETS_DIR / "un-welcome.bmp")


def build_header():
    """Franja superior de paginas internas (directory, instfiles). Gradiente horizontal."""
    img = horizontal_gradient(HEADER_W, HEADER_H, GRAD_TOP, GRAD_MID, GRAD_BOT)

    # Logo pequeno pegado a la derecha
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        max_h = int(HEADER_H * 0.65)
        max_w = int(HEADER_W * 0.20)
        ratio = min(max_w / logo.width, max_h / logo.height)
        nw, nh = max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio))
        logo = logo.resize((nw, nh), Image.LANCZOS)
        px = HEADER_W - nw - 8
        py = (HEADER_H - nh) // 2
        img.paste(logo, (px, py), logo)

    # Texto "NeuroFlex" a la izquierda
    font = load_font(13, bold=True)
    draw = ImageDraw.Draw(img)
    draw.text((8, (HEADER_H - 13) // 2), "NeuroFlex", font=font, fill=WHITE)

    save_bmp(img, ASSETS_DIR / "header.bmp")


def build_ico():
    """Icono multi-resolucion para el EXE (fondo transparente)."""
    sizes = [256, 48, 32, 16]
    frames = []
    for size in sizes:
        frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        if LOGO_PATH.exists():
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo = logo.resize((size, size), Image.LANCZOS)
            frame.paste(logo, (0, 0), logo)
        else:
            # Fallback: cuadrado con gradiente + N
            grad = vertical_gradient(size, size, GRAD_TOP, GRAD_MID, GRAD_BOT)
            frame = Image.new("RGBA", (size, size))
            frame.paste(grad, (0, 0))
            draw = ImageDraw.Draw(frame)
            try:
                font = ImageFont.truetype("arialbd.ttf", int(size * 0.6))
            except (OSError, IOError):
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), "N", font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((size - tw) // 2, (size - th) // 2), "N", font=font, fill=WHITE)
        frames.append(frame)

    ico_path = ASSETS_DIR / "neuroflex.ico"
    frames[0].save(str(ico_path), format="ICO", sizes=[(s, s) for s in sizes])
    print(f"  [ok] {ico_path.name}  ({len(sizes)} sizes: {sizes})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Generando assets NSIS MUI2 para NeuroFlex...")
    build_welcome()
    build_un_welcome()
    build_header()
    build_ico()
    print("\nListo. Arrastra installer/neuroflex.nsi sobre makensis.exe para compilar.")


if __name__ == "__main__":
    main()