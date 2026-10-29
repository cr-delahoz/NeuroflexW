"""Builds the audit log PDF export using the shared PDF engine.

Aimed at non-technical reviewers (e.g. compliance staff): a cover page,
a fixed glossary page explaining each column, and a landscape table of
events with action codes/metadata translated to plain Spanish via
audit.action_labels.
"""

from django.conf import settings
from django.utils import timezone

from reports.pdf_engine import (
    MARGIN_X,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    COLOR_BODY,
    COLOR_PARAGRAPH,
    COLOR_PETROLEO,
    COLOR_SECONDARY,
    append_ops,
    assemble_pdf_bytes,
    draw_text_block,
    format_datetime,
    load_png_for_pdf,
    render_content_pages,
    render_footer_ops,
    render_grid_table_pages,
)

from .action_labels import METADATA_KEY_LABELS, humanize_action, humanize_metadata


CONFIDENTIALITY_NOTE = "Documento confidencial - uso interno de NeuroFlex."

GLOSSARY_ENTRIES = [
    ("Fecha y hora", "Momento exacto en que ocurrio el evento, segun el reloj del servidor."),
    (
        "Usuario responsable",
        "La persona que realizo la accion. Si aparece 'Sistema', el evento fue "
        "generado por un proceso automatico sin un usuario detras.",
    ),
    (
        "Accion realizada",
        "Que se hizo (por ejemplo, crear un usuario o aprobar un informe), "
        "descrito en lenguaje simple en vez del codigo interno del sistema.",
    ),
    (
        "Recurso afectado",
        "Sobre que elemento del sistema se realizo la accion (un usuario, "
        "una sesion, un informe, etc.) y su identificador cuando aplica.",
    ),
    ("Resultado", "Si la accion se completo correctamente o si ocurrio un error."),
    ("Direccion IP", "La direccion de red desde la que se realizo la accion, cuando esta disponible."),
    (
        "Detalle adicional",
        "Informacion complementaria sobre el evento, traducida a lenguaje simple.",
    ),
]

NOT_LOGGED_NOTE = (
    "Por politica de NeuroFlex, este registro nunca incluye: contrasenas, "
    "datos completos del paciente, JSON clinicos, features completas del "
    "modelo de Machine Learning ni rutas locales de archivos."
)

TABLE_HEADERS = ["Fecha", "Usuario", "Accion", "Recurso", "Resultado", "IP", "Detalle"]
TABLE_COLUMN_WIDTHS = [75, 85, 130, 100, 55, 75, 200]


def _load_logo():
    logo_path = (
        settings.BASE_DIR / "static" / "images" / "brand" / "logo-neuroflex-color.png"
    )
    if not logo_path.exists():
        return None
    try:
        return load_png_for_pdf(logo_path)
    except Exception:
        return None


def _actor_label(log):
    if log.actor:
        full_name = log.actor.get_full_name().strip()
        return full_name or log.actor.username
    return "Sistema"


def _resource_label(log):
    if log.resource_id:
        return f"{log.resource_type} / {log.resource_id}"
    return log.resource_type or "No disponible"


def _result_label(log):
    return "Correcto" if log.result == "SUCCESS" else "Error"


def _format_filters(filters_applied):
    if not filters_applied:
        return "Sin filtros aplicados."
    # humanize_metadata already knows how to flatten a "filters" dict (same
    # shape AuditLogExportView logs for audit_exported); reuse it here
    # instead of duplicating the formatting rules, then drop its own label.
    prefix = f"{METADATA_KEY_LABELS['filters']}: "
    humanized = humanize_metadata({"filters": filters_applied})
    return humanized[len(prefix):] if humanized.startswith(prefix) else humanized


def build_cover_page(*, total_events, filters_applied, generated_at, logo_image):
    operations = []
    if logo_image:
        target_width = 200
        scale = target_width / logo_image["width"]
        target_height = logo_image["height"] * scale
        x = (PAGE_WIDTH - target_width) / 2
        y = PAGE_HEIGHT - target_height - 80
        operations.append(
            f"q {target_width:.2f} 0 0 {target_height:.2f} {x:.2f} {y:.2f} cm /Im1 Do Q"
        )

    operations.extend(
        draw_text_block(
            MARGIN_X,
            480,
            ["Registro de Auditoria - NeuroFlex"],
            font="F2",
            size=22,
            leading=24,
            color=COLOR_PETROLEO,
        )
    )
    operations.extend(
        draw_text_block(
            MARGIN_X,
            448,
            ["Exportacion para revision no tecnica"],
            font="F1",
            size=12,
            leading=14,
            color=COLOR_SECONDARY,
        )
    )

    summary_lines = [
        f"Generado: {format_datetime(generated_at)}",
        f"Eventos incluidos: {total_events}",
        f"Filtros aplicados: {_format_filters(filters_applied)}",
    ]
    operations.extend(
        draw_text_block(
            MARGIN_X, 390, summary_lines, font="F1", size=12, leading=18, color=COLOR_BODY
        )
    )
    operations.extend(
        draw_text_block(
            MARGIN_X,
            270,
            [
                "Este documento traduce el registro tecnico de auditoria a lenguaje",
                "simple. La pagina siguiente explica el significado de cada columna",
                "antes de mostrar la tabla de eventos.",
            ],
            font="F1",
            size=11,
            leading=16,
            color=COLOR_PARAGRAPH,
        )
    )
    return "\n".join(operations).encode("latin-1")


def build_glossary_elements():
    elements = [{"type": "section", "title": "Glosario de columnas"}]
    for label, description in GLOSSARY_ENTRIES:
        elements.append({"type": "table", "rows": [(label, description)]})
    elements.append({"type": "section", "title": "Que NO se registra en auditoria"})
    elements.append({"type": "paragraph", "text": NOT_LOGGED_NOTE})
    return elements


def build_table_rows(logs):
    return [
        [
            format_datetime(log.created_at),
            _actor_label(log),
            humanize_action(log.action),
            _resource_label(log),
            _result_label(log),
            log.ip_address or "No disponible",
            humanize_metadata(log.metadata),
        ]
        for log in logs
    ]


def build_audit_log_pdf(logs, filters_applied):
    """Build the audit export PDF. `logs` is any iterable/queryset of
    AuditLog rows; `filters_applied` mirrors what AuditLogExportView (the
    CSV export) already logs as metadata for `audit_exported`.
    """
    logs = list(logs)
    generated_at = timezone.now()
    logo_image = _load_logo()

    cover_stream = build_cover_page(
        total_events=len(logs),
        filters_applied=filters_applied,
        generated_at=generated_at,
        logo_image=logo_image,
    )
    glossary_streams = render_content_pages(build_glossary_elements())

    table_page_width, table_page_height = PAGE_HEIGHT, PAGE_WIDTH  # landscape
    table_streams = render_grid_table_pages(
        TABLE_HEADERS,
        TABLE_COLUMN_WIDTHS,
        build_table_rows(logs),
        page_width=table_page_width,
        page_height=table_page_height,
        title="Registro de eventos",
        empty_message="No hay eventos en el rango seleccionado.",
    )

    page_streams = [cover_stream, *glossary_streams, *table_streams]
    page_sizes = (
        [(PAGE_WIDTH, PAGE_HEIGHT)] * (1 + len(glossary_streams))
        + [(table_page_width, table_page_height)] * len(table_streams)
    )

    total_pages = len(page_streams)
    page_streams = [
        append_ops(
            stream,
            render_footer_ops(
                index + 1, total_pages, CONFIDENTIALITY_NOTE, page_width=size[0]
            ),
        )
        for index, (stream, size) in enumerate(zip(page_streams, page_sizes))
    ]

    return assemble_pdf_bytes(page_streams, logo_image=logo_image, page_sizes=page_sizes)
