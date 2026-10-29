# NeuroFlex Dashboard

## Objetivo

Aplicación web Django para administrar usuarios, visualizar sesiones clínicas de NeuroFlex VR, ejecutar inferencia de Machine Learning controlada y gestionar solicitudes/aprobación/generación de informes PDF.

Actualmente usa sesiones JSON locales; en el futuro serán reemplazadas por una API REST. El sistema debe mantener compatibilidad con ambas fuentes sin modificar la lógica de negocio.

---

## Arquitectura

- **Frontend:** Django Templates + Tailwind CSS. Interfaz clara, sobria y accesible para profesionales de la salud.
- **Backend:** Django, servicios desacoplados, apps independientes por dominio.
- **Persistencia:** SQLite (desarrollo), posible PostgreSQL futuro.

Las vistas nunca consumen datos directamente — siempre mediante servicios.

### Apps y responsabilidades

| App | Responsabilidad |
|-----|----------------|
| `accounts` | Autenticación, usuario personalizado, roles, permisos |
| `dashboard` | Dashboards ADMIN y SPECIALIST |
| `audit` | Auditoría, exportación CSV y PDF |
| `reports` | Solicitud, aprobación, rechazo y generación de PDF |
| `clinical_sessions` | Proveedor de sesiones, normalización, carga |
| `ml` | Carga del modelo, features, inferencia, interpretación provisional |
| `updater` | Actualización interna con barra de progreso, polling, batch sin consola |

---

## Roles

### ADMIN
- **Puede:** crear/activar/desactivar usuarios, aprobar/rechazar solicitudes PDF, consultar/exportar auditoría.
- **No puede:** ver pacientes, sesiones, resultados cognitivos ni descargar informes clínicos.

### SPECIALIST
- **Puede:** ver sesiones y detalle, ejecutar inferencia, ver resultado provisional, solicitar/descargar PDF aprobado.
- **No puede:** administrar usuarios, consultar auditoría, aprobar solicitudes.

---

## Machine Learning

- **Modelo activo:** `ml/model_artifacts/neuroflex_3classes_model.onnx`, modo `three_class_provisional`.
- Predice bandas de desempeño `bajo`, `medio` o `alto` derivadas de `Precision`; no predice deterioro cognitivo.
- **NO constituye validación clínica.** No presentar como diagnóstico ni evaluación definitiva; comunicar que es un resultado provisional.

### Flujo de inferencia

```
Session → Feature Builder → Model Loader → Inference Service → Result Interpreter → Dashboard / PDF
```

No mezclar responsabilidades.

### Feature Builder

`ml/services/performance_feature_builder.py` construye las 19 entradas del modelo, incluidas `tiempo_total`, `ratio_aciertos` y las transformaciones logarítmicas. Requiere las diez métricas de sesión del modelo y `dominant_hand`/`ManoPredominante` desde los metadatos del paciente.

Toda transformación ocurre únicamente dentro de Feature Builder — nunca en vistas, templates, PDF ni dashboard. Imputación, escalado y codificación categórica están incluidos en el grafo ONNX.

### Inference Service

Carga el modelo ONNX vía ONNX Runtime, ejecuta inferencia y devuelve clase y probabilidades estructuradas. No interpreta clínicamente ni genera HTML/PDF.

### Contrato de inferencia

La salida debe contener: `predicted_class`, `classes`, `probabilities`, `predicted_class_probability`, `legacy_label`, `interpretation_status`, `warnings`. No eliminar claves existentes.

---

## Fuente de datos

- **Actual:** `clinical_sessions/data/local_sessions/` (LocalSessionProvider)
- **Futuro:** API REST (ApiSessionProvider)
- El reemplazo del proveedor no debe modificar vistas, permisos, dashboards, PDF ni auditoría.

---

## Informes PDF

```
SPECIALIST → Solicita → ADMIN → Aprueba → Generación PDF → Descarga SPECIALIST
```

El administrador nunca descarga informes clínicos.

---

## Auditoría

Registra: inicio/cierre de sesión, creación/activación/desactivación de usuarios, solicitud/aprobación/rechazo de informes, generación PDF, ejecución de inferencia.

**No registrar:** contraseñas, datos completos del paciente, JSON clínicos, features completas, rutas locales.

La auditoría no puede modificarse desde la aplicación.

---

## Retroalimentación de carga

- **Spinners en botones, paginación y acciones** — implementados con Tailwind + JS vanilla (`static/js/ui-feedback.js`).
- **Componente reusable:** `templates/components/loading_spinner.html`.
- **Updater:** barra de progreso con polling a `/updater/progress/<job_id>/`. Ejecuta batch sin mostrar consola Windows. Archivos: `updater/jobs.py`, `updater/services.py`, `updater/views.py`.

---

## Interfaz

Priorizar simplicidad, legibilidad, accesibilidad. Público objetivo: profesionales de salud >40 años.

- **Usar:** Tailwind CSS.
- **Evitar:** Bootstrap, Material UI, animaciones excesivas, efectos glass, interfaces oscuras completas.
- **Colores:** blanco, azul petróleo, azul medio.

---

## Restricciones

No implementar todavía (salvo solicitud explícita): API definitiva, auth clínica, Docker, Kubernetes, Redis, Celery, PostgreSQL, microservicios.

---

## Carpetas ocultas y archivos de trabajo local

- **No crear ni versionar carpetas ocultas** de trabajo local del agente (carpetas que comienzan con punto: `.superpowers/`, `.cache/`, `.worktrees/`, etc.) ni ningún otro archivo de estado/scratch interno.
- Esas carpetas son **estrictamente locales**: no se seleccionan en `git add`, no se commitean (ni con `git add -f`) y no se suben al remoto.
- Al crearlas añadirlas de inmediato a `.gitignore`; si alguien las ha commiteado por error, eliminarlas del repo con `git rm -r --cached <carpeta>` en el siguiente commit.

---

## Calidad

Después de cada cambio: ejecutar `python manage.py check` y las pruebas relacionadas. Informar archivos modificados, pruebas ejecutadas y problemas pendientes.

---

## Objetivo de evolución

Cuando la API esté disponible, solo reemplazar el proveedor de datos. Toda la lógica de autenticación, permisos, dashboards, auditoría, PDF y ML debe permanecer intacta. La migración debe requerir cambios mínimos sin afectar la experiencia del usuario.
