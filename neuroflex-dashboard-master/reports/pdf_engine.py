"""Shared, dependency-free PDF construction primitives.

This project has no PDF library installed (no reportlab/weasyprint/fpdf) -
PDFs are built by hand: raw %PDF-1.4 objects, content-stream operators, a
manual PNG decoder for the brand logo, and a manual xref/trailer. This
module holds the pieces that are not specific to any single document
(fonts, page geometry, text/pagination helpers, PNG decoding, and final
byte assembly) so any PDF builder in the project (clinical reports, audit
exports, future ones) can share them instead of duplicating the format
plumbing.
"""

import struct
import zlib
from datetime import datetime
from pathlib import Path
from textwrap import wrap

from django.utils import timezone

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_X = 72
BOTTOM_MARGIN = 60

COLOR_PETROLEO = "0.06 0.16 0.24"
COLOR_SECONDARY = "0.35 0.41 0.47"
COLOR_BODY = "0 0 0"
COLOR_MUTED = "0.24 0.28 0.34"
COLOR_PARAGRAPH = "0.12 0.14 0.18"

FONT_REGULAR_ID = 3
FONT_BOLD_ID = 4


def escape_pdf_text(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def format_datetime(value):
    """Render a datetime (or already-stringy value) the way every PDF in
    this project shows dates: "%d/%m/%Y %H:%M", localized, or a fallback."""
    if not value:
        return "No disponible"

    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")

    return str(value)


def draw_text_block(x, y, lines, *, font="F1", size=11, leading=15, color=COLOR_BODY):
    operations = [
        "BT",
        f"/{font} {size} Tf",
        f"{color} rg",
        f"{leading} TL",
        f"{x} {y} Td",
    ]
    for index, line in enumerate(lines):
        if index > 0:
            operations.append("T*")
        operations.append(f"({escape_pdf_text(line)}) Tj")
    operations.append("ET")
    return operations


def append_ops(stream_bytes, ops):
    """Append extra content-stream operators (e.g. a footer) to an already
    rendered/encoded page stream. Safe because each draw_text_block call is
    a self-contained BT/ET block."""
    if not ops:
        return stream_bytes
    return stream_bytes + b"\n" + "\n".join(ops).encode("latin-1")


def render_footer_ops(page_number, total_pages, note, *, page_width=PAGE_WIDTH, margin_x=MARGIN_X):
    ops = draw_text_block(
        margin_x,
        32,
        [f"Pagina {page_number} de {total_pages}"],
        font="F1",
        size=8,
        leading=10,
        color=COLOR_MUTED,
    )
    ops.extend(
        draw_text_block(
            page_width - margin_x - 260,
            32,
            [note],
            font="F1",
            size=8,
            leading=10,
            color=COLOR_MUTED,
        )
    )
    return ops


def render_content_pages(elements):
    """Paginate a list of {"type": "section"|"table"|"paragraph", ...}
    elements into portrait (612x792) page content streams. Unchanged from
    the original report-only implementation - only relocated here."""
    pages = []
    current_ops = []
    y = 750

    def flush_page():
        nonlocal current_ops, y
        pages.append("\n".join(current_ops).encode("latin-1"))
        current_ops = []
        y = 750

    for element in elements:
        if element["type"] == "section":
            block_height = 34
            if y - block_height < 60 and current_ops:
                flush_page()
            current_ops.append("0.06 0.16 0.24 RG")
            current_ops.append(f"72 {y-6} m 540 {y-6} l S")
            current_ops.extend(
                draw_text_block(
                    72,
                    y,
                    [element["title"]],
                    font="F2",
                    size=15,
                    leading=18,
                    color="0.06 0.16 0.24",
                )
            )
            y -= block_height
        elif element["type"] == "table":
            for label, value in element["rows"]:
                combined_lines = wrap(f"{label}: {value}", width=88) or [f"{label}: {value}"]
                row_height = len(combined_lines) * 14 + 8
                if y - row_height < 60 and current_ops:
                    flush_page()
                current_ops.extend(
                    draw_text_block(
                        72,
                        y,
                        combined_lines,
                        font="F1",
                        size=10.5,
                        leading=13,
                        color="0 0 0",
                    )
                )
                y -= row_height
            y -= 10
        elif element["type"] == "paragraph":
            wrapped_lines = wrap(element["text"], width=88)
            block_height = len(wrapped_lines) * 14 + 10
            if y - block_height < 60 and current_ops:
                flush_page()
            current_ops.extend(
                draw_text_block(
                    72,
                    y,
                    wrapped_lines,
                    font="F1",
                    size=10.5,
                    leading=14,
                    color="0.12 0.14 0.18",
                )
            )
            y -= block_height

    if current_ops:
        flush_page()
    return pages


def render_grid_table_pages(
    headers,
    column_widths,
    rows,
    *,
    page_width,
    page_height,
    margin_x=48,
    bottom_margin=50,
    font_size=7,
    header_font_size=8,
    leading=9,
    title=None,
    empty_message="No hay datos para mostrar.",
):
    """Paginate `rows` (list of lists of pre-formatted strings) into a
    multi-column grid table, repeating the header row on every page.

    Column wrapping is approximate (Helvetica has no fixed character
    width per point size), sized conservatively so text does not overflow
    into the next column. `column_widths` are relative weights, scaled to
    fill the usable page width.
    """
    usable_width = page_width - 2 * margin_x
    total_declared = sum(column_widths) or 1
    scale = usable_width / total_declared
    scaled_widths = [w * scale for w in column_widths]
    column_x = []
    cursor = margin_x
    for width in scaled_widths:
        column_x.append(cursor)
        cursor += width

    def chars_per_column(width_pts, size):
        return max(8, int(width_pts / (size * 0.52)))

    top_y = page_height - 56
    pages = []
    current_ops = []
    y = top_y

    def draw_header(y_pos):
        ops = []
        for label, x, width in zip(headers, column_x, scaled_widths):
            wrapped = wrap(str(label), width=chars_per_column(width, header_font_size)) or [str(label)]
            ops.extend(
                draw_text_block(
                    x,
                    y_pos,
                    wrapped,
                    font="F2",
                    size=header_font_size,
                    leading=leading + 1,
                    color=COLOR_PETROLEO,
                )
            )
        ops.append(f"{COLOR_PETROLEO} RG")
        ops.append(f"{margin_x} {y_pos - 4} m {margin_x + usable_width} {y_pos - 4} l S")
        return ops

    def flush_page():
        nonlocal current_ops, y
        pages.append("\n".join(current_ops).encode("latin-1"))
        current_ops = []
        y = top_y

    if title:
        current_ops.extend(
            draw_text_block(margin_x, y, [title], font="F2", size=13, leading=16, color=COLOR_PETROLEO)
        )
        y -= 26

    current_ops.extend(draw_header(y))
    y -= (leading * 2 + 6)

    if not rows:
        current_ops.extend(
            draw_text_block(margin_x, y, [empty_message], font="F1", size=10, leading=13, color=COLOR_BODY)
        )
        flush_page()
        return pages

    for row in rows:
        wrapped_cells = [
            wrap(str(value), width=chars_per_column(width, font_size)) or [str(value) or "-"]
            for value, width in zip(row, scaled_widths)
        ]
        row_lines = max(len(cell) for cell in wrapped_cells) if wrapped_cells else 1
        row_height = row_lines * leading + 6

        if y - row_height < bottom_margin:
            flush_page()
            current_ops.extend(draw_header(y))
            y -= (leading * 2 + 6)

        for cell_lines, x in zip(wrapped_cells, column_x):
            current_ops.extend(
                draw_text_block(x, y, cell_lines, font="F1", size=font_size, leading=leading, color=COLOR_BODY)
            )
        y -= row_height

    if current_ops:
        flush_page()
    return pages


def png_paeth_predictor(left, up, up_left):
    prediction = left + up - up_left
    p_left = abs(prediction - left)
    p_up = abs(prediction - up)
    p_up_left = abs(prediction - up_left)

    if p_left <= p_up and p_left <= p_up_left:
        return left
    if p_up <= p_up_left:
        return up
    return up_left


def undo_png_filters(raw_data, width, height, bytes_per_pixel):
    stride = width * bytes_per_pixel
    output = bytearray()
    previous_row = bytearray(stride)
    position = 0

    for _ in range(height):
        filter_type = raw_data[position]
        position += 1
        row = bytearray(raw_data[position : position + stride])
        position += stride

        if filter_type == 1:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                row[i] = (row[i] + left) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                row[i] = (row[i] + previous_row[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up = previous_row[i]
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up = previous_row[i]
                up_left = previous_row[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                row[i] = (row[i] + png_paeth_predictor(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"Unsupported PNG filter type {filter_type}.")

        output.extend(row)
        previous_row = row

    return bytes(output)


def load_png_for_pdf(image_path):
    raw = Path(image_path).read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Unsupported image format for PDF logo.")

    position = 8
    width = height = bit_depth = color_type = None
    compressed_data = bytearray()

    while position < len(raw):
        chunk_length = struct.unpack(">I", raw[position : position + 4])[0]
        chunk_type = raw[position + 4 : position + 8]
        chunk_data = raw[position + 8 : position + 8 + chunk_length]
        position += chunk_length + 12

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, flt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if compression != 0 or flt != 0 or interlace != 0:
                raise ValueError("Unsupported PNG compression/filter/interlace settings.")
        elif chunk_type == b"IDAT":
            compressed_data.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError("Only 8-bit RGB/RGBA PNG logos are supported.")

    bytes_per_pixel = 3 if color_type == 2 else 4
    decoded = undo_png_filters(
        zlib.decompress(bytes(compressed_data)),
        width,
        height,
        bytes_per_pixel,
    )

    if color_type == 2:
        return {
            "width": width,
            "height": height,
            "color_space": "/DeviceRGB",
            "data": zlib.compress(decoded),
            "alpha": None,
        }

    rgb = bytearray()
    alpha = bytearray()
    for index in range(0, len(decoded), 4):
        rgb.extend(decoded[index : index + 3])
        alpha.append(decoded[index + 3])

    return {
        "width": width,
        "height": height,
        "color_space": "/DeviceRGB",
        "data": zlib.compress(bytes(rgb)),
        "alpha": zlib.compress(bytes(alpha)),
    }


def assemble_pdf_bytes(page_streams, *, logo_image=None, page_sizes=None):
    """Assemble already-rendered page content streams into final PDF bytes:
    Catalog/Pages/Font(/XObject) objects, per-page Page/Contents objects,
    and the xref/trailer. Generalized from the original report-only
    build_pdf_bytes: `page_sizes` lets callers mix page dimensions (e.g. a
    portrait cover + landscape data table) in one document; it defaults to
    US Letter portrait for every page when omitted.
    """
    if page_sizes is None:
        page_sizes = [(PAGE_WIDTH, PAGE_HEIGHT)] * len(page_streams)

    font_regular_id = FONT_REGULAR_ID
    font_bold_id = FONT_BOLD_ID
    next_object_id = 5
    image_object_id = None
    alpha_object_id = None
    if logo_image:
        image_object_id = next_object_id
        next_object_id += 1
        if logo_image["alpha"] is not None:
            alpha_object_id = next_object_id
            next_object_id += 1

    page_object_ids = []
    content_object_ids = []
    for _ in page_streams:
        page_object_ids.append(next_object_id)
        next_object_id += 1
        content_object_ids.append(next_object_id)
        next_object_id += 1

    objects = []
    objects.append("1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    page_refs = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects.append(
        f"2 0 obj << /Type /Pages /Kids [{page_refs}] /Count {len(page_object_ids)} >> endobj\n"
    )
    objects.append(
        f"{font_regular_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        f"/Encoding /WinAnsiEncoding >> endobj\n"
    )
    objects.append(
        f"{font_bold_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        f"/Encoding /WinAnsiEncoding >> endobj\n"
    )

    if logo_image:
        image_dictionary = (
            f"{image_object_id} 0 obj << /Type /XObject /Subtype /Image /Width {logo_image['width']} "
            f"/Height {logo_image['height']} /ColorSpace {logo_image['color_space']} /BitsPerComponent 8 "
            f"/Filter /FlateDecode /Length {len(logo_image['data'])}"
        )
        if alpha_object_id:
            image_dictionary += f" /SMask {alpha_object_id} 0 R"
        image_dictionary += " >> stream\n"
        objects.append(
            image_dictionary.encode("latin-1").decode("latin-1")
            + logo_image["data"].decode("latin-1")
            + "\nendstream endobj\n"
        )
        # Objects must be serialized in ascending object-id order because the
        # xref offsets are emitted in that same order. Writing the soft mask
        # (id + 1) before the image made some viewers repair the xref table;
        # Edge's PDF viewer may not recover that malformed reference.
        if alpha_object_id:
            objects.append(
                f"{alpha_object_id} 0 obj << /Type /XObject /Subtype /Image /Width {logo_image['width']} "
                f"/Height {logo_image['height']} /ColorSpace /DeviceGray /BitsPerComponent 8 "
                f"/Filter /FlateDecode /Length {len(logo_image['alpha'])} >> stream\n".encode(
                    "latin-1"
                ).decode("latin-1")
                + logo_image["alpha"].decode("latin-1")
                + "\nendstream endobj\n"
            )

    for page_id, content_id, stream, (page_w, page_h) in zip(
        page_object_ids, content_object_ids, page_streams, page_sizes
    ):
        resources = (
            f"<< /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >>"
        )
        if logo_image:
            resources += f" /XObject << /Im1 {image_object_id} 0 R >>"
        resources += " >>"
        objects.append(
            f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {content_id} 0 R /Resources {resources} >> endobj\n"
        )
        objects.append(
            f"{content_id} 0 obj << /Length {len(stream)} >> stream\n".encode(
                "latin-1"
            ).decode("latin-1")
            + stream.decode("latin-1")
            + "\nendstream endobj\n"
        )

    pdf = "%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf.encode("latin-1")))
        pdf += obj

    xref_offset = len(pdf.encode("latin-1"))
    total_objects = len(objects) + 1
    pdf += f"xref\n0 {total_objects}\n"
    pdf += "0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += (
        f"trailer << /Root 1 0 R /Size {total_objects} >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )
    return pdf.encode("latin-1")
