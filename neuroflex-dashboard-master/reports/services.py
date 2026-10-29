from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from textwrap import wrap

from audit.models import AuditLog
from audit.services import log_event
from ml.services import predict_cognitive_result

from .models import ReportRequest
from .pdf_engine import (
    assemble_pdf_bytes,
    draw_text_block,
    format_datetime as format_datetime_for_report,
    load_png_for_pdf,
    render_content_pages,
)


ACTIVE_REPORT_STATUSES = (
    ReportRequest.Status.PENDING,
    ReportRequest.Status.APPROVED,
    ReportRequest.Status.GENERATING,
    ReportRequest.Status.GENERATED,
)

SESSION_REPORT_STATE_MAP = {
    ReportRequest.Status.PENDING: {
        "code": "PENDING",
        "label": "Pendiente de aprobacion",
        "tone": "warning",
        "action_label": "Solicitud pendiente",
    },
    ReportRequest.Status.APPROVED: {
        "code": "APPROVED",
        "label": "Aprobado",
        "tone": "success",
        "action_label": "Aprobado",
    },
    ReportRequest.Status.GENERATING: {
        "code": "GENERATING",
        "label": "Generando informe",
        "tone": "warning",
        "action_label": "Generando informe",
    },
    ReportRequest.Status.GENERATED: {
        "code": "GENERATED",
        "label": "Informe disponible",
        "tone": "success",
        "action_label": "Descargar informe",
    },
    ReportRequest.Status.REJECTED: {
        "code": "REJECTED",
        "label": "Solicitud rechazada",
        "tone": "danger",
        "action_label": "Solicitar informe",
    },
    ReportRequest.Status.ERROR: {
        "code": "ERROR",
        "label": "Error de generacion",
        "tone": "danger",
        "action_label": "Solicitar informe",
    },
}


def get_active_duplicate_queryset(*, requested_by, session_id):
    return ReportRequest.objects.filter(
        requested_by=requested_by,
        session_id=session_id,
        status__in=ACTIVE_REPORT_STATUSES,
    )


def build_report_status_map_for_user(user, session_ids):
    requests = (
        ReportRequest.objects.filter(requested_by=user, session_id__in=session_ids)
        .order_by("session_id", "-requested_at", "-id")
    )
    latest_by_session = {}
    for request in requests:
        latest_by_session.setdefault(request.session_id, request)

    status_map = {}
    for session_id, request in latest_by_session.items():
        state = dict(SESSION_REPORT_STATE_MAP[request.status])
        state["request_id"] = request.pk
        state["rejection_reason"] = request.rejection_reason
        status_map[session_id] = state

    return status_map


def build_generated_report_map_for_orphaned_sessions(session_ids):
    """Latest GENERATED, ownerless ReportRequest per session_id.

    Used by the admin "unassociated sessions" view to offer a download link
    only for reports an admin is actually allowed to fetch (see
    AdminReportDownloadView, which requires requested_by__isnull=True).
    """
    requests = (
        ReportRequest.objects.filter(
            requested_by__isnull=True,
            session_id__in=session_ids,
            status=ReportRequest.Status.GENERATED,
        )
        .order_by("session_id", "-requested_at", "-id")
    )
    latest_by_session = {}
    for request in requests:
        latest_by_session.setdefault(request.session_id, request)
    return latest_by_session


def create_report_request(*, form, requested_by, session_snapshot):
    report_request = form.save(commit=False)
    report_request.requested_by = requested_by
    report_request.status = ReportRequest.Status.PENDING
    report_request.session_snapshot = session_snapshot
    report_request.save()
    return report_request


def auto_generate_report(report_request, *, actor, ip_address):
    """Skip human approval for specialists with can_generate_pdf_without_approval.

    reviewed_by stays None (no admin acted) but reviewed_at is set so the PDF
    traceability section can tell this apart from a report that is still
    genuinely unreviewed.
    """
    report_request.status = ReportRequest.Status.APPROVED
    report_request.reviewed_by = None
    report_request.reviewed_at = timezone.now()
    report_request.rejection_reason = ""
    report_request.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"]
    )
    log_event(
        actor=actor,
        action="pdf_auto_generated",
        resource_type="report_request",
        resource_id=report_request.pk,
        result=AuditLog.Result.SUCCESS,
        ip_address=ip_address,
        metadata={"session_id": report_request.session_id},
    )
    generate_report_file(report_request, actor=actor, ip_address=ip_address)


def generate_orphan_report(*, session, admin_user, ip_address):
    """Generate a PDF for an orphaned (specialist-less) session, on admin action.

    `session` is a SpecialistSession whose specialist was deleted and that has
    locally cached metrics. The report has requested_by=None (its specialist is
    gone) and reviewed_by=admin_user, so the PDF traceability shows the admin
    who generated it. Skips human approval (it is the admin exception). Returns
    the ReportRequest; check its .status for the outcome (generate_report_file
    swallows errors into ERROR status).
    """
    snapshot = {
        "session_id": session.session_id,
        "metrics": session.metrics,
        "created_at": session.confirmed_at.isoformat() if session.confirmed_at else None,
        "status": "completed",
    }
    report_request = ReportRequest.objects.create(
        session_id=session.session_id,
        requested_by=None,
        reviewed_by=admin_user,
        reviewed_at=timezone.now(),
        status=ReportRequest.Status.APPROVED,
        session_snapshot=snapshot,
    )
    log_event(
        actor=admin_user,
        action="unassociated_report_generated",
        resource_type="report_request",
        resource_id=report_request.pk,
        result=AuditLog.Result.SUCCESS,
        ip_address=ip_address,
        metadata={"session_id": session.session_id},
    )
    generate_report_file(report_request, actor=admin_user, ip_address=ip_address)
    return report_request


def get_requester_display(report_request):
    if report_request.requested_by is None:
        return {
            "display_name": "Especialista eliminado",
            "username": "No disponible",
            "show_username": False,
            "profession": None,
        }

    full_name = report_request.requested_by.get_full_name().strip()
    requester_profession = report_request.requested_by.profession
    if full_name:
        return {
            "display_name": full_name,
            "username": report_request.requested_by.username,
            "show_username": True,
            "profession": requester_profession,
        }
    return {
        "display_name": report_request.requested_by.username,
        "username": report_request.requested_by.username,
        "show_username": False,
        "profession": requester_profession,
    }


def build_cognitive_result_items(cognitive_result):
    if not cognitive_result.get("available"):
        return []

    rows = [
        ("Banda de desempeño estimada", cognitive_result["predicted_class"]),
        (
            "Probabilidad tecnica asociada a la clase predicha",
            cognitive_result.get("technical_confidence_label", "No disponible"),
        ),
        (
            "Probabilidades estimadas por banda",
            "; ".join(
                f"{label}: {probability}"
                for label, probability in cognitive_result.get(
                    "probability_labels", {}
                ).items()
            ) or "No disponible",
        ),
        (
            "Estado de interpretacion",
            "Provisional; requiere validacion clinica",
        ),
        ("Modelo utilizado", cognitive_result.get("model_name", "No disponible")),
        (
            "Fecha de procesamiento",
            format_datetime_for_report(cognitive_result.get("processed_at")),
        ),
    ]
    if cognitive_result.get("legacy_label"):
        rows.insert(
            0,
            (
                "Resultado provisional",
                cognitive_result["legacy_label"],
            ),
        )
    return rows


def build_section_elements(report_request, normalized_session):
    requester = get_requester_display(report_request)
    if report_request.reviewed_by:
        admin_name = (
            report_request.reviewed_by.get_full_name().strip()
            or report_request.reviewed_by.username
        )
    elif report_request.reviewed_at:
        admin_name = "Autogenerado sin aprobacion (permiso del especialista)"
    else:
        admin_name = "No disponible"

    elements = [
        {"type": "section", "title": "Identificacion del informe"},
        {
            "type": "table",
            "rows": [
                ("Identificador del informe", report_request.pk),
                ("Identificador de sesion", normalized_session["session_id"]),
                (
                    "Fecha de evaluacion",
                    format_datetime_for_report(normalized_session["evaluated_at"]),
                ),
                (
                    "Fecha y hora de generacion",
                    format_datetime_for_report(report_request.generated_at),
                ),
                ("Estado del informe", report_request.get_status_display()),
            ],
        },
        {"type": "section", "title": "Especialista solicitante"},
        {
            "type": "table",
            "rows": [
                ("Especialista solicitante", requester["display_name"]),
                (
                    "Profesion",
                    requester["profession"].name
                    if requester.get("profession")
                    else "Sin profesion asignada",
                ),
                *(
                    [("Usuario", requester["username"])]
                    if requester["show_username"]
                    else []
                ),
                (
                    "Fecha de solicitud",
                    format_datetime_for_report(report_request.requested_at),
                ),
            ],
        },
        {"type": "section", "title": "Informacion general del paciente"},
    ]

    patient_rows = []
    patient = normalized_session["patient"]
    if patient.get("internal_id"):
        patient_rows.append(("Identificador interno", patient["internal_id"]))
    if patient.get("age") is not None:
        patient_rows.append(("Edad", patient["age"]))
    if patient.get("dominant_hand"):
        patient_rows.append(("Mano dominante", patient["dominant_hand"]))
    patient_rows.append(
        (
            "Fecha de evaluacion",
            format_datetime_for_report(normalized_session["evaluated_at"]),
        )
    )
    if normalized_session["metrics"].get("scene_type") is not None:
        patient_rows.append(("Tipo de escena", normalized_session["metrics"]["scene_type"]))
    elements.append({"type": "table", "rows": patient_rows})

    elements.append({"type": "section", "title": "Resumen de desempeno"})
    elements.append(
        {
            "type": "table",
            "rows": [
                (item["label"], item["value"])
                for item in normalized_session["performance_items"]
            ],
        }
    )

    elements.append({"type": "section", "title": "Resultado del modelo"})
    if normalized_session["cognitive_result"].get("available"):
        elements.append(
            {
                "type": "table",
                "rows": build_cognitive_result_items(
                    normalized_session["cognitive_result"]
                ),
            }
        )
        elements.append(
            {
                "type": "paragraph",
                "text": (
                    "Este resultado es una estimacion experimental de banda de "
                    "desempeno y no cuenta con validacion clinica. No constituye "
                    "un diagnostico y debe interpretarse con cautela."
                ),
            }
        )
        for warning in normalized_session["cognitive_result"].get("warnings", []):
            elements.append({"type": "paragraph", "text": warning})
    else:
        elements.append(
            {
                "type": "paragraph",
                "text": normalized_session["cognitive_result"].get(
                    "user_message",
                    "No fue posible calcular el resultado automatizado con la informacion disponible en esta sesion.",
                ),
            }
        )

    if report_request.specialist_observation:
        elements.append({"type": "section", "title": "Observaciones del especialista"})
        elements.append(
            {
                "type": "paragraph",
                "text": report_request.specialist_observation,
            }
        )

    elements.extend(
        [
            {"type": "section", "title": "Trazabilidad"},
            {
                "type": "table",
                "rows": [
                    ("Identificador de solicitud", report_request.pk),
                    ("Especialista solicitante", requester["display_name"]),
                    ("Username", requester["username"]),
                    (
                        "Fecha y hora de solicitud",
                        format_datetime_for_report(report_request.requested_at),
                    ),
                    ("Aprobado administrativamente por", admin_name),
                    (
                        "Fecha y hora de aprobacion",
                        format_datetime_for_report(report_request.reviewed_at),
                    ),
                    (
                        "Fecha y hora de generacion",
                        format_datetime_for_report(report_request.generated_at),
                    ),
                    (
                        "Origen de los datos",
                        "API de NeuroFlex (snapshot tomado al momento de la solicitud).",
                    ),
                ],
            },
            {"type": "section", "title": "Aviso"},
            {
                "type": "paragraph",
                "text": (
                    "Este informe contiene una estimacion automatizada basada "
                    "en datos obtenidos durante una sesion de evaluacion con "
                    "realidad virtual. El resultado no constituye un "
                    "diagnostico medico y debe interpretarse junto con otros "
                    "antecedentes clinicos y profesionales."
                ),
            },
            {
                "type": "paragraph",
                "text": (
                    "Documento generado a partir de los datos de la sesion "
                    "obtenidos desde la API de NeuroFlex al momento de la "
                    "solicitud."
                ),
            },
        ]
    )
    return elements


PDF_LEFT = 72
PDF_RIGHT = 540
PDF_NAVY = "0.06 0.16 0.24"
PDF_BLUE = "0.10 0.32 0.60"
PDF_BORDER = "0.72 0.79 0.89"
PDF_HEADER_FILL = "0.86 0.90 0.95"
PDF_ROW_FILL = "0.96 0.97 0.99"


def _pdf_rect(x, y, width, height, *, fill=None, stroke=None, line_width=1):
    ops = ["q"]
    if fill:
        ops.append(f"{fill} rg")
    if stroke:
        ops.extend([f"{stroke} RG", f"{line_width} w"])
    operator = "B" if fill and stroke else "f" if fill else "S"
    ops.extend([f"{x} {y} {width} {height} re {operator}", "Q"])
    return ops


def _pdf_line(x1, y1, x2, y2, *, color=PDF_BORDER, line_width=1):
    return ["q", f"{color} RG", f"{line_width} w", f"{x1} {y1} m {x2} {y2} l S", "Q"]


def _pdf_text(x, y, value, *, bold=False, size=9, color=PDF_NAVY, leading=None):
    lines = value if isinstance(value, list) else [str(value)]
    return draw_text_block(
        x, y, lines, font="F2" if bold else "F1", size=size,
        leading=leading or size + 3, color=color,
    )


def _report_identifier(report_request):
    return f"INF-{report_request.pk:04d}"


def _display_value(value):
    return "No disponible" if value in (None, "") else str(value)


def _section(ops, number, title, y):
    ops.extend(_pdf_text(PDF_LEFT, y, f"{number}  {title}", bold=True, size=15))
    ops.extend(_pdf_line(PDF_LEFT, y - 11, PDF_RIGHT, y - 11))
    return y - 27


def _table(ops, y, headers, rows, widths, *, font_size=8.5, row_height=24):
    x = PDF_LEFT
    table_width = sum(widths)
    ops.extend(_pdf_rect(x, y - row_height, table_width, row_height, fill=PDF_HEADER_FILL, stroke=PDF_BORDER))
    current_x = x
    for header, width in zip(headers, widths):
        ops.extend(_pdf_text(current_x + 8, y - 16, header, bold=True, size=font_size))
        current_x += width
    y -= row_height
    for index, row in enumerate(rows):
        height = row_height
        wrapped = []
        for value, width in zip(row, widths):
            wrapped.append(wrap(_display_value(value), max(12, int(width / (font_size * .52)))) or [""])
            height = max(height, len(wrapped[-1]) * (font_size + 2) + 10)
        ops.extend(_pdf_rect(x, y - height, table_width, height, fill=PDF_ROW_FILL if index % 2 else None, stroke=PDF_BORDER))
        current_x = x
        for lines, width in zip(wrapped, widths):
            ops.extend(_pdf_text(current_x + 8, y - 15, lines, size=font_size, leading=font_size + 2))
            current_x += width
        y -= height
    current_x = x
    for width in widths[:-1]:
        current_x += width
        ops.extend(_pdf_line(current_x, y, current_x, y + sum([row_height] + [row_height for _ in rows]), color=PDF_BORDER))
    return y


def _page_header(ops, report_id, *, continuation=False):
    ops.extend(_pdf_rect(48, 756, 516, 22, fill="0.99 0.96 0.88"))
    ops.extend(_pdf_line(48, 756, 564, 756, color="0.91 0.61 0.05", line_width=1.3))
    ops.extend(_pdf_text(72, 769, "INFORME DE SESION - DOCUMENTO DE USO PROFESIONAL", bold=True, size=9, color="0.42 0.25 0.02"))
    ops.extend(_pdf_text(PDF_LEFT, 731, "PLATAFORMA DE REALIDAD VIRTUAL PARA LA ESTIMULACION COGNITIVA", bold=True, size=9, color=PDF_BLUE))
    title = "Informe de sesion - continuacion" if continuation else "Informe de sesion"
    ops.extend(_pdf_text(PDF_LEFT, 704, title, bold=True, size=21))
    ops.extend(_pdf_text(421, 727, f"Informe {report_id}", size=9, color="0.20 0.32 0.48"))
    ops.extend(_pdf_line(PDF_LEFT, 682, PDF_RIGHT, 682, color=PDF_NAVY, line_width=1.1))
    return 662


def _page_footer(ops, report_id, session_id, page_number, total_pages=3):
    ops.extend(_pdf_text(PDF_LEFT, 32, f"{report_id}  |  Sesion {session_id}", size=7.5, color="0.20 0.32 0.48"))
    ops.extend(_pdf_text(465, 32, f"Pagina {page_number} de {total_pages}", size=7.5, color="0.20 0.32 0.48"))


def _cover_page(report_id, session_id, evaluated_at, logo_image):
    """A restrained professional cover, separated from the clinical content."""
    ops = []
    ops.extend(_pdf_rect(0, 0, 612, 792, fill="0.97 0.99 1.0"))
    ops.extend(_pdf_rect(0, 0, 22, 792, fill="0.10 0.32 0.60"))
    ops.extend(_pdf_rect(22, 0, 7, 792, fill="0.96 0.54 0.16"))
    if logo_image:
        target_width = 390
        target_height = logo_image["height"] * target_width / logo_image["width"]
        ops.append(f"q {target_width:.2f} 0 0 {target_height:.2f} 111 548 cm /Im1 Do Q")
    ops.extend(_pdf_text(92, 430, "INFORME DE SESION", bold=True, size=27, color=PDF_NAVY))
    ops.extend(_pdf_text(92, 396, "Documento de uso profesional", size=13, color="0.20 0.32 0.48"))
    ops.extend(_pdf_line(92, 365, 520, 365, color="0.10 0.32 0.60", line_width=1.2))
    details = [
        f"Informe: {report_id}",
        f"Sesion: {session_id}",
        f"Fecha de evaluacion: {evaluated_at}",
    ]
    ops.extend(_pdf_text(92, 325, details, size=11, color=PDF_NAVY, leading=22))
    ops.extend(_pdf_rect(92, 150, 428, 88, fill="0.91 0.95 0.99"))
    ops.extend(_pdf_text(112, 205, "Resumen profesional de la sesion de estimulacion cognitiva", bold=True, size=11, color=PDF_BLUE))
    ops.extend(_pdf_text(112, 180, ["La informacion presentada en las paginas siguientes debe interpretarse", "en el contexto de la evaluacion clinica realizada por el especialista."], size=9, color="0.20 0.32 0.48", leading=13))
    ops.extend(_pdf_text(92, 55, "NeuroFlex VR - plataforma de realidad virtual para la estimulacion cognitiva", size=8, color="0.20 0.32 0.48"))
    return "\n".join(ops).encode("latin-1")


def _metric_rows(performance_items):
    labels = {
        "Precision": "Precision de interaccion", "TiempoActivoTarea": "Tiempo activo en la tarea",
        "CantAciertasTotales": "Aciertos totales", "ObjetosInteractuadosCorrectamente": "Objetos interactuados correctamente",
        "TiempoRespuestaPararse": "Tiempo de respuesta al levantarse", "TiempoRespuestaPregunta1": "Tiempo de respuesta pregunta 1",
        "TiempoRespuestaPregunta2": "Tiempo de respuesta pregunta 2", "TiempoRespuestaPregunta3": "Tiempo de respuesta pregunta 3",
        "TiempoCapturarNumero": "Tiempo de captura de numero", "TiempoTutorial": "Tiempo de tutorial",
    }
    rows = []
    for item in performance_items:
        label, value = item["label"], item["value"]
        if label in {"TipoEscena", "Edad", "ManoPredominante", "Anno", "Mes", "Dia"}:
            continue
        suffix = " %" if label == "Precision" else " s" if label.startswith("Tiempo") else " conteo" if label in {"CantAciertasTotales", "ObjetosInteractuadosCorrectamente"} else ""
        rows.append((labels.get(label, label), f"{value}{suffix}", "Sin referencia disponible"))
    return rows or [("Sin metricas disponibles", "No disponible", "Sin referencia disponible")]


def _metric_card(ops, x, y, title, value, *, accent="0.10 0.32 0.60"):
    """Render a compact key-performance card for quick clinical scanning."""
    ops.extend(_pdf_rect(x, y - 58, 222, 58, fill="0.96 0.98 1.0", stroke=PDF_BORDER))
    ops.extend(_pdf_rect(x, y - 58, 5, 58, fill=accent))
    ops.extend(_pdf_text(x + 16, y - 18, title, size=8, color="0.20 0.32 0.48"))
    ops.extend(_pdf_text(x + 16, y - 42, value, bold=True, size=15, color=PDF_NAVY))


def _timeline(ops, y, events):
    """Render report traceability as a timeline instead of a dense table."""
    line_x = 96
    ops.extend(_pdf_line(line_x, y - 13, line_x, y - (len(events) - 1) * 51 - 13, color="0.66 0.78 0.91", line_width=2))
    for index, (title, owner, moment) in enumerate(events):
        event_y = y - index * 51
        ops.extend(_pdf_rect(line_x - 5, event_y - 18, 10, 10, fill=PDF_BLUE))
        ops.extend(_pdf_text(116, event_y - 7, title, bold=True, size=10))
        ops.extend(_pdf_text(116, event_y - 23, f"{owner}  -  {moment}", size=8.5, color="0.20 0.32 0.48"))
    return y - len(events) * 51


def build_pdf_bytes(report_request, normalized_session, logo_image=None):
    """Build a cover and specialist-focused clinical session report."""
    patient = normalized_session["patient"]
    report_id = _report_identifier(report_request)
    session_id = _display_value(normalized_session["session_id"])
    evaluated_at = format_datetime_for_report(normalized_session["evaluated_at"])
    cognitive = normalized_session["cognitive_result"]
    probability = cognitive.get("predicted_class_probability")
    probability = float(probability) if probability is not None else 0.0
    requester = get_requester_display(report_request)
    requester_account = report_request.requested_by
    specialist_email = (
        (requester_account.email or requester_account.username)
        if requester_account
        else "No disponible"
    )
    specialist_profession = (
        requester["profession"].name
        if requester.get("profession")
        else "Sin profesion asignada"
    )

    cover = _cover_page(report_id, session_id, evaluated_at, logo_image)
    first = []
    y = _page_header(first, report_id)
    y = _section(first, 1, "Identificacion de la sesion", y)
    y = _table(first, y, ["Campo", "Valor", "Campo", "Valor"], [
        ("Especialista", specialist_email, "Profesion", specialist_profession),
        ("Sesion", session_id, "Fecha de evaluacion", evaluated_at),
        ("Tipo de escena", normalized_session["metrics"].get("scene_type"), "Edad", patient.get("age")),
        ("Mano predominante", patient.get("dominant_hand"), "", ""),
    ], [82, 154, 104, 128]) - 22
    y = _section(first, 2, "Indicador provisional del modelo", y)
    label = cognitive.get("legacy_label") or cognitive.get("predicted_class") or "Resultado no disponible"
    first.extend(_pdf_rect(PDF_LEFT, y - 82, 468, 76, fill="0.92 0.96 1.0", stroke="0.57 0.72 0.88"))
    first.extend(_pdf_rect(PDF_LEFT, y - 82, 7, 76, fill=PDF_BLUE))
    first.extend(_pdf_text(94, y - 25, "Resultado automatizado provisional", bold=True, size=8.5, color=PDF_BLUE))
    first.extend(_pdf_text(94, y - 47, label, bold=True, size=13))
    first.extend(_pdf_text(94, y - 67, "No constituye un diagnostico. Requiere interpretacion profesional.", size=8.5, color="0.20 0.32 0.48"))
    first.extend(_pdf_text(418, y - 33, f"{probability:.3f}", bold=True, size=16, color=PDF_BLUE))
    first.extend(_pdf_text(392, y - 50, "Puntuacion tecnica", size=7.5, color="0.20 0.32 0.48"))
    y -= 99
    metric_rows = _metric_rows(normalized_session["performance_items"])
    y = _section(first, 3, "Desempeno observado", y)
    primary_metrics = metric_rows[:4]
    for index, (metric, value, _) in enumerate(primary_metrics):
        x = PDF_LEFT + (index % 2) * 240
        card_y = y - (index // 2) * 68
        _metric_card(first, x, card_y, metric, value, accent=PDF_BLUE if index < 2 else "0.96 0.54 0.16")
    y -= 136
    _page_footer(first, report_id, session_id, 2, total_pages=4)

    detail = []
    y = _page_header(detail, report_id, continuation=True)
    y = _section(detail, 4, "Detalle complementario", y)
    complementary_rows = metric_rows[4:]
    if complementary_rows:
        y = _table(detail, y, ["Indicador", "Valor observado", "Referencia provisional"], complementary_rows, [200, 110, 158], row_height=18) - 18
    else:
        detail.extend(_pdf_text(PDF_LEFT, y - 20, "Sin indicadores complementarios disponibles.", size=9, color="0.20 0.32 0.48"))
    _page_footer(detail, report_id, session_id, 3, total_pages=4)

    second = []
    y = _page_header(second, report_id, continuation=True)
    y = _section(second, 5, "Observaciones del especialista", y)
    observation = report_request.specialist_observation or "Sin observaciones registradas."
    observation_lines = wrap(observation, 78)
    observation_height = max(50, len(observation_lines) * 12 + 20)
    second.extend(_pdf_rect(PDF_LEFT, y - observation_height + 5, 468, observation_height, fill="0.99 0.97 0.92", stroke="0.92 0.76 0.42"))
    second.extend(_pdf_text(88, y - 14, observation_lines, size=9, color=PDF_NAVY, leading=12))
    y -= observation_height + 20
    y = _section(second, 6, "Trazabilidad del documento", y)
    if report_request.reviewed_by:
        admin = (
            report_request.reviewed_by.get_full_name().strip()
            or report_request.reviewed_by.username
        )
    elif report_request.reviewed_at:
        admin = "Autogenerado sin aprobacion (permiso del especialista)"
    else:
        admin = "Sistema"
    y = _timeline(second, y, [
        ("Sesion aplicada", requester["display_name"], evaluated_at),
        ("Informe solicitado", requester["display_name"], format_datetime_for_report(report_request.requested_at)),
        ("Emision autorizada", admin, format_datetime_for_report(report_request.reviewed_at)),
        ("Documento emitido", "Sistema", format_datetime_for_report(report_request.generated_at)),
    ]) - 2
    second.extend(_pdf_rect(PDF_LEFT, y - 33, 468, 31, fill="0.96 0.98 1.0"))
    second.extend(_pdf_text(84, y - 14, "Los identificadores son seudonimizados; los datos de contacto se conservan solo en la auditoria autenticada.", size=8, color="0.20 0.32 0.48"))
    y -= 54
    y = _section(second, 7, "Advertencias", y)
    warning_lines = [
        "Este documento no es un diagnostico. Contiene una estimacion automatizada basada en datos de",
        "comportamiento registrados durante una sesion de estimulacion cognitiva con realidad virtual.",
        "El modelo se encuentra en validacion. Su interpretacion clinica esta pendiente de validacion.",
        "Las referencias de desempeno no estan disponibles todavia; su ausencia no debe reemplazarse por valores",
        "normativos o inferidos.",
    ]
    # Reserve independent padding for the heading and the final text baseline.
    # The former height only accounted for body lines and clipped descenders
    # in the last warning line in some PDF viewers.
    height = len(warning_lines) * 12 + 42
    second.extend(_pdf_rect(PDF_LEFT, y - height + 4, 468, height, fill="1.0 0.96 0.86", stroke="0.91 0.61 0.05"))
    second.extend(_pdf_text(88, y - 15, "INFORMACION IMPORTANTE", bold=True, size=8.5, color="0.55 0.28 0.00"))
    second.extend(_pdf_text(88, y - 31, warning_lines, size=8.5, color="0.22 0.17 0.10", leading=12))
    _page_footer(second, report_id, session_id, 4, total_pages=4)
    return assemble_pdf_bytes([cover, "\n".join(first).encode("latin-1"), "\n".join(detail).encode("latin-1"), "\n".join(second).encode("latin-1")], logo_image=logo_image)


def _sorted_metric_items(metrics):
    items = []
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, float):
            value = round(value, 2)
        items.append({"label": key, "value": value})
    return items


def normalize_snapshot_for_report(snapshot):
    """Build the normalized_session shape build_pdf_bytes expects, from a
    ReportRequest.session_snapshot captured at request time (see
    reports.views.ReportRequestCreateView).
    """
    metrics = snapshot.get("metrics") or {}
    patient_info = snapshot.get("patient_info") or {}
    dominant_hand = (
        patient_info.get("dominant_hand")
        or patient_info.get("ManoPredominante")
        or patient_info.get("dominantHand")
        or metrics.get("ManoPredominante")
    )
    age = patient_info.get("age") or patient_info.get("Edad") or metrics.get("Edad")
    return {
        "session_id": snapshot.get("session_id"),
        "evaluated_at": parse_datetime(snapshot.get("created_at") or ""),
        "patient": {
            "internal_id": None,
            "age": age,
            "dominant_hand": dominant_hand,
        },
        "metrics": {"scene_type": metrics.get("TipoEscena")},
        "performance_items": _sorted_metric_items(metrics),
        "cognitive_result": predict_cognitive_result(
            metrics, patient_info=patient_info
        ),
    }


def generate_report_file(report_request, *, actor, ip_address):
    report_request.status = ReportRequest.Status.GENERATING
    report_request.technical_error_message = ""
    report_request.save(update_fields=["status", "technical_error_message"])
    log_event(
        actor=actor,
        action="report_generation_started",
        resource_type="report_request",
        resource_id=report_request.pk,
        result=AuditLog.Result.SUCCESS,
        ip_address=ip_address,
        metadata={"session_id": report_request.session_id},
    )

    try:
        normalized_session = normalize_snapshot_for_report(report_request.session_snapshot)
        report_request.generated_at = timezone.now()
        logo_image = None
        logo_path = (
            settings.BASE_DIR
            / "static"
            / "images"
            / "brand"
            / "logo-neuroflex-textlateral-color.png"
        )
        if logo_path.exists():
            logo_image = load_png_for_pdf(logo_path)
        pdf_bytes = build_pdf_bytes(report_request, normalized_session, logo_image=logo_image)
        filename = f"report-{report_request.pk}.pdf"
        report_request.file.save(filename, ContentFile(pdf_bytes), save=False)
        report_request.status = ReportRequest.Status.GENERATED
        report_request.save(update_fields=["status", "generated_at", "file"])
        log_event(
            actor=actor,
            action="report_generated",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.SUCCESS,
            ip_address=ip_address,
            metadata={"session_id": report_request.session_id},
        )
    except Exception as exc:
        report_request.status = ReportRequest.Status.ERROR
        report_request.technical_error_message = str(exc)
        report_request.save(update_fields=["status", "technical_error_message"])
        log_event(
            actor=actor,
            action="report_generation_failed",
            resource_type="report_request",
            resource_id=report_request.pk,
            result=AuditLog.Result.FAILURE,
            ip_address=ip_address,
            metadata={"session_id": report_request.session_id},
        )
