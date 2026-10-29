# Auditoría técnica — NeuroFlex Dashboard

> **Fecha:** 2026-08-12  
> **Alcance:** análisis read-only del proyecto Django en `C:\Users\lucas\Desktop\neuroflex-dashboard`.  
> **Metodología:** visión general → 4 investigaciones paralelas (arquitectura, seguridad, rendimiento/datos, configuración/despliegue) → revisión cruzada por reviewer → validaciones técnicas controladas con builder.  
> **Restricción:** no se modificó ningún archivo del proyecto.

---

## Resumen ejecutivo

El proyecto es una aplicación Django 6.0.6 de escritorio (PyInstaller + NSIS + webview) orientada a profesionales de la salud. La arquitectura por apps está bien definida y la separación ML (FeatureBuilder / InferenceService / ResultInterpreter / ModelLoader) respeta el contrato funcional. Los flujos de autorización por rol y la mitigación de IDOR en informes y sesiones están correctamente implementados.

Los riesgos principales se concentran en tres áreas:

1. **Actualizador automático (`updater`)**: endpoints sin autenticación que descargan y ejecutan un EXE con cierre forzoso del proceso. Es la superficie de ataque más grave.
2. **Configuración/empaquetado**: valores por defecto inseguros (`DEBUG=True`, `SECRET_KEY` predecible), instalador silencioso que escribe un `.env` vacío y documentación de CI que no existe.
3. **Deuda técnica acumulada**: orquestación de negocio en vistas, datos locales muertos, ORM directo en vistas que deberían usar servicios, y generación síncrona de PDF/ML dentro del request.

Las áreas mejor implementadas son: autorización basada en roles, saneamiento de auditoría, mitigación de IDOR en descargas/sesiones, uso de timeouts en clientes HTTP y verificación SHA256 del instalador.

---

## Hallazgos priorizados

| Prioridad | Severidad | Área | Problema | Impacto | Ubicación |
|---|---|---|---|---|---|
| P1 | ALTO | Seguridad / Despliegue | Updater sin autenticación: descarga y ejecuta EXE | RCE local, DoS | `updater/views.py:22-98`, `updater/urls.py:6-8` |
| P2 | ALTO | Configuración / Despliegue | NSIS `/S` escribe `.env` con campos vacíos | Instalación rota silenciosamente | `installer/neuroflex.nsi:147-248` |
| P3 | ALTO | Configuración | Pipeline GitHub Actions documentado pero inexistente | Release manual, riesgo de error | `docs/updater-readme.md:9-17` |
| P4 | ALTO | Arquitectura | Orquestación de negocio en vista de solicitud de informe | Difícil de testear y reutilizar | `reports/views.py:60-160` |
| P5 | MEDIO | Seguridad | XSS por `innerHTML` con datos de API externa | Robo de sesión, posible RCE vía updater | `static/js/active_sessions.js:24-48` |
| P6 | MEDIO | Seguridad | Open redirect en creación de informes | Phishing | `reports/views.py:150-152` |
| P7 | MEDIO | Seguridad | Borrado local no elimina cuenta Cognito | Cuenta eliminada sigue operativa | `accounts/views.py:548-555`, `accounts/services.py:190-252` |
| P8 | MEDIO | Seguridad | Sesión Django desalineada de tokens Cognito | Acceso prolongado tras expiración Cognito | `accounts/views.py:66-70`, `config/settings.py` |
| P9 | MEDIO | Seguridad / Despliegue | Cadena de confianza del updater depende solo de GitHub | Compromiso de release = RCE masivo | `updater/services.py:38-115` |
| P10 | MEDIO | Seguridad / Despliegue | Updater: nombres fijos en `%TEMP%`, sin firma ni comparación de versión | Race condition, downgrade, ejecución no confiable | `updater/views.py:57-66`, `updater/views.py:101-123` |
| P11 | MEDIO | Configuración | `GITHUB_TOKEN` en `.env` plano | Credencial legible por cualquier proceso | `installer/neuroflex.nsi:247`, `config/settings.py:10-11` |
| P12 | MEDIO | Configuración | Defaults inseguros (`DEBUG=True`, `SECRET_KEY` predecible) | Fuga de información, clave conocida | `config/settings.py:13-17`, `.env:1-2` |
| P13 | MEDIO | Rendimiento | Auditoría sin paginación + `{{ logs\|length }}` | Degradación lineal, uso de memoria | `audit/views.py:60-67`, `templates/audit/log_list.html:49` |
| P14 | MEDIO | Rendimiento | Generación PDF + inferencia ML síncronas en request | Timeouts, interfaz bloqueada | `reports/views.py:233-237`, `reports/services.py:523-576` |
| P15 | MEDIO | Datos | TOCTOU en asociación de sesión | Sesión asignada al especialista equivocado | `clinical_sessions/services/specialist_session_service.py:63-85` |
| P16 | MEDIO | Datos | Unique parcial permite duplicados huérfanos | Informes clínicos duplicados | `reports/models.py:45-53` |
| P17 | MEDIO | Rendimiento / Datos | `cache_session_metrics` escribe N veces por listado | Contención SQLite, latencia | `clinical_sessions/views.py:94-95` |
| P18 | MEDIO | Estabilidad | `RuntimeError` no capturado en updater | 500 en condición de concurrencia | `updater/views.py:30`, `updater/jobs.py:42-46` |
| P19 | MEDIO | Arquitectura | Vistas acceden al ORM directamente | Rompe la regla "vistas → servicios" | `dashboard/views.py`, `reports/views.py`, `audit/views.py`, etc. |
| P20 | MEDIO | Arquitectura | `CognitoAuthenticationForm.clean()` de ~130 líneas | Form acoplado a integración remota | `accounts/forms.py:68-198` |
| P21 | MEDIO | Arquitectura | `RoleRequiredMixin` vive en app `dashboard` | Acoplamiento invertido entre apps | `dashboard/views.py:10-21` |
| P22 | MEDIO | Configuración | Sin configuración de logging | Errores de producción invisibles | `config/settings.py` |
| P23 | MEDIO | Configuración | `runserver` como servidor de producción | Deuda técnica de despliegue | `neuroflex_launcher.py:185-190` |
| P24 | MEDIO | Configuración | `pywebview>=5.0` sin pin exacto | Builds no reproducibles | `requirements.txt:3` |
| P25 | MEDIO | Seguridad | Fixture `FAKE_SESSIONS` en código de producción | Acceso a sesiones ajenas si se activa | `external_session_client.py:13-75` |
| P26 | MEDIO | Configuración | Elevación admin en instalador + datos en LOCALAPPDATA | Perfiles de datos divididos, privilegios innecesarios | `installer/neuroflex.nsi:216` |
| P27 | BAJO | Arquitectura | Datos locales (`LocalSessionProvider`) no se usan | Código muerto, doc desactualizada | `clinical_sessions/services/session_data_service.py`, `local_session_provider.py` |
| P28 | BAJO | Configuración | `STATIC_ROOT` no definido | `collectstatic` inutilizable | `config/settings.py:104-108` |
| P29 | BAJO | Seguridad | Cabeceras de seguridad no configuradas | Cookies sin Secure, sin CSP/HSTS | `config/settings.py:39-47` |
| P30 | BAJO | Configuración | Dependencias sin uso en runtime (`xgboost`, `pandas`) | Confusión de entornos | `requirements.txt:5-6` |
| P31 | BAJO | Rendimiento | Check de updater en cada carga de página | 2 llamadas GitHub síncronas | `static/updater/updater.js:12` |
| P32 | BAJO | Rendimiento | Exports de auditoría materializan queryset | Memoria innecesaria | `audit/views.py:115,140` |
| P33 | BAJO | Estabilidad | Jobs de updater en memoria | Estado perdido al reiniciar | `updater/jobs.py:19-21` |
| P34 | BAJO | Arquitectura | Duplicación de ordenamiento de métricas | Deuda técnica menor | `reports/services.py:493-500`, `clinical_sessions/views.py:47-63` |

---

## Detalle de hallazgos

### P1 — Updater sin autenticación ni autorización

**Severidad:** ALTO  
**Categoría:** Seguridad / Despliegue  
**Ubicación:** `updater/views.py:22-98`, `updater/urls.py:6-8`

**Evidencia:**  
`UpdateCheckView` y `UpdateRunView` heredan de `View` plano. `UpdateRunView.post` llama a `has_update_available()`, descarga el instalador, lo renombra a `installer.exe`, escribe un `.bat` en `%TEMP%` y lo ejecuta con `subprocess.Popen(["cmd", "/c", ...])`. Finalmente invoca `os._exit(0)`. Validación con `Client()` anónimo: `GET /updater/check/` → `200`; `POST /updater/run/` → `403` solo por CSRF (no por auth); `GET /updater/progress/...` → `404` sin login.

**Problema:** Cualquier proceso local (o JavaScript ejecutado en el contexto de la app) puede iniciar una actualización forzada y cerrar la aplicación. CSRF mitiga ataques remotos simples, pero no constituye autorización.

**Impacto:** Denegación de servicio trivial y, si se combina con XSS (P5), ejecución remota de código en el equipo del usuario.

**Escenario en que ocurre:** Un enlace malicioso o un XSS en el dashboard lee el `csrftoken` y hace `fetch("/updater/run/")`; el equipo descarga y ejecuta un binario controlado por el atacante.

**Posible forma de explotación:** XSS → robo de CSRF → POST a `/updater/run/` → descarga/ejecución de EXE → compromiso total del host.

**Solución recomendada:** Aplicar `LoginRequiredMixin` + `RoleRequiredMixin` (solo ADMIN debería poder disparar actualizaciones) en `/updater/run/`; agregar un token de sesión webview para `/updater/check/` y `/updater/progress/`; no confiar solo en CSRF.

**Archivos/componentes que habría que modificar:** `updater/views.py`, `updater/urls.py`, `static/updater/updater.js`, posiblemente `dashboard/views.py` (mover `RoleRequiredMixin`).

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Medio

### P2 — Instalación silenciosa escribe `.env` vacío

**Severidad:** ALTO  
**Categoría:** Configuración / Despliegue  
**Ubicación:** `installer/neuroflex.nsi:147-194`, `237-248`

**Evidencia:** El instalador NSIS lee `valApiUrl`, `valClientId` y `valGitHubToken` en páginas custom. En modo `/S` esas páginas se omiten, pero la sección de escritura del `.env` sigue usando esas variables sin inicializar por defecto.

**Problema:** Una actualización silenciosa deja el archivo `.env` con `NEUROFLEX_API_BASE_URL=`, `COGNITO_CLIENT_ID=` y `GITHUB_TOKEN=` vacíos.

**Impacto:** La aplicación deja de funcionar: Cognito no autentica, la API no responde y el updater no puede consultar GitHub.

**Escenario en que ocurre:** El updater dispara `/S` para actualizar; tras el reinicio, el usuario no puede iniciar sesión.

**Solución recomendada:** En modo silencioso, copiar el `.env` existente de `%LOCALAPPDATA%\NeuroFlex\data\` o exigir parámetros `/DApiUrl=...`, etc. Nunca escribir un `.env` incompleto.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P3 — Pipeline GitHub Actions documentado pero inexistente

**Severidad:** ALTO  
**Categoría:** Configuración / Despliegue  
**Ubicación:** `docs/updater-readme.md:9-17`

**Evidencia:** La documentación afirma que GitHub Actions compila, empaqueta y publica releases automáticamente. No existe directorio `.github/` ni workflow en el repositorio.

**Problema:** El proceso de release es manual y no está automatizado como se describe.

**Impacto:** Riesgo de publicar `latest.json` o SHA256 desactualizados; el updater puede fallar silenciosamente.

**Solución recomendada:** Crear `.github/workflows/release.yml` o corregir la documentación para reflejar el proceso manual actual.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Bajo

### P4 — Orquestación de negocio en vista de solicitud de informe

**Severidad:** ALTO  
**Categoría:** Arquitectura  
**Ubicación:** `reports/views.py:60-160`

**Evidencia:** `ReportRequestCreateView.post` realiza validación de sesión remota, detección de duplicados (pre-check + `IntegrityError`), construcción del snapshot, auditoría y auto-generación del informe, todo dentro de la vista.

**Problema:** La vista contiene lógica de negocio que no es reutilizable ni fácil de probar fuera del ciclo HTTP.

**Impacto:** Cambios en el flujo requieren tocar la vista; duplicidad de fuentes de verdad para duplicados.

**Solución recomendada:** Mover el flujo a `reports/services.py` (ej. `request_report_for_session(...)`); la vista solo debe adaptar request/response.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P5 — XSS por `innerHTML` con datos de API externa

**Severidad:** MEDIO  
**Categoría:** Seguridad  
**Ubicación:** `static/js/active_sessions.js:24-48`

**Evidencia:** `renderSessions()` asigna `container.innerHTML = ...` con interpolación directa de `session.session_id`, `session.display_code` y `session.vr_user_email`.

**Problema:** No se escapan los datos antes de insertarlos en el DOM.

**Impacto:** Una API comprometida o un dato con HTML/JS permite ejecutar código en el dashboard del especialista.

**Solución recomendada:** Usar `document.createElement` + `textContent`, o escapar los valores antes de `innerHTML`.

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Bajo

### P6 — Open redirect en creación de informes

**Severidad:** MEDIO  
**Categoría:** Seguridad  
**Ubicación:** `reports/views.py:150-152`

**Evidencia:** `next_url = request.POST.get("next"); if next_url: return redirect(next_url)`. El template refleja el valor en un campo oculto.

**Problema:** `redirect()` acepta URLs absolutas; no se valida el destino.

**Impacto:** Phishing: un enlace `/reports/new/?next=https://evil.com` redirige a un sitio externo tras una operación aparentemente legítima.

**Solución recomendada:** Validar con `django.utils.http.url_has_allowed_host_and_scheme` y hosts permitidos, o eliminar la redirección arbitraria.

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Bajo

### P7 — Borrado local no elimina cuenta Cognito

**Severidad:** MEDIO  
**Categoría:** Seguridad / Datos  
**Ubicación:** `accounts/views.py:548-555`, `accounts/services.py:190-252`

**Evidencia:** `UserDeleteView.post` solo hace `target_user.delete()` con un TODO que reconoce que Cognito no se borra. El servicio de reconciliación recrea usuarios locales desde el listado remoto.

**Problema:** Eliminar el usuario local no revoca el acceso real.

**Impacto:** Un usuario "eliminado" puede volver a iniciar sesión y recuperar su rol.

**Escenario en que ocurre:** ADMIN borra un especialista; el especialista vuelve a loguearse y es recreado localmente.

**Solución recomendada:** Deshabilitar/eliminar la cuenta Cognito antes de borrar localmente, o marcar `is_active=False` y excluir del sync.

**Complejidad estimada:** Alta  
**Riesgo de regresión:** Alto

### P8 — Sesión Django desalineada de tokens Cognito

**Severidad:** MEDIO  
**Categoría:** Seguridad  
**Ubicación:** `accounts/views.py:66-70`, `config/settings.py`

**Evidencia:** Los tokens Cognito se guardan en sesión Django. No hay `SESSION_COOKIE_AGE`, `SESSION_EXPIRE_AT_BROWSER_CLOSE` ni renovación con refresh token.

**Problema:** La sesión Django dura 14 días por defecto, mucho más que el access token de Cognito.

**Impacto:** Acceso local persistente a dashboards/informes aunque Cognito haya expirado el token.

**Escenario en que ocurre:** Usuario cierra el webview; en un equipo compartido, otro usuario reabre la app y sigue autenticado.

**Solución recomendada:** Alinear `SESSION_COOKIE_AGE` con la expiración del token, `SESSION_EXPIRE_AT_BROWSER_CLOSE=True`, renovar tokens o forzar re-login.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P9 — Cadena de confianza del updater depende solo de GitHub

**Severidad:** MEDIO  
**Categoría:** Seguridad / Despliegue  
**Ubicación:** `updater/services.py:38-115`

**Evidencia:** El SHA256 esperado se obtiene de `latest.json`, un asset del mismo release de GitHub que el EXE.

**Problema:** El hash solo verifica integridad, no autenticidad. Si el repo se compromete, hash y binario cambian juntos.

**Impacto:** Compromiso de la cuenta/release de GitHub → RCE masivo en todos los clientes.

**Escenario en que ocurre:** Cuenta de GitHub hackeada → release malicioso con `latest.json` actualizado → clientes instalan malware.

**Solución recomendada:** Verificar firma de código (Authenticode) o distribuir hash/firma por canal independiente.

**Complejidad estimada:** Alta  
**Riesgo de regresión:** Medio

### P10 — Updater: nombres fijos en `%TEMP%`, sin firma ni comparación de versión

**Severidad:** MEDIO  
**Categoría:** Seguridad / Despliegue  
**Ubicación:** `updater/views.py:57-66`, `updater/views.py:101-123`

**Evidencia:** Escribe siempre `installer.exe` y `%TEMP%\neuroflex_update.bat`. No valida firma ni compara versión descargada vs instalada.

**Problema:** Race condition por nombres fijos; posible downgrade; no hay verificación de identidad del binario.

**Impacto:** Ejecución de instalador incorrecto o antiguo.

**Solución recomendada:** Usar directorio temporal exclusivo por job; validar firma Authenticode; comparar semvers antes de ejecutar.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P11 — `GITHUB_TOKEN` en `.env` plano

**Severidad:** MEDIO  
**Categoría:** Configuración / Seguridad  
**Ubicación:** `installer/neuroflex.nsi:247`, `config/settings.py:10-11`

**Evidencia:** El instalador escribe `GITHUB_TOKEN=` en `%LOCALAPPDATA%\NeuroFlex\data\.env`. El updater lo lee desde allí.

**Problema:** Cualquier proceso del usuario puede leer el token.

**Impacto:** Fuga de credencial con acceso a releases.

**Solución recomendada:** Usar releases públicos (sin token) o almacenar credencial en el almacén seguro de Windows con permisos mínimos.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Bajo

### P12 — Defaults inseguros en settings

**Severidad:** MEDIO  
**Categoría:** Configuración / Seguridad  
**Ubicación:** `config/settings.py:13-17`, `.env:1-2`

**Evidencia:** `SECRET_KEY` tiene fallback `django-insecure-change-me-before-production`; `DEBUG` default `True`. El `.env` local contiene `DJANGO_SECRET_KEY=change-me` y `DJANGO_DEBUG=True`.

**Problema:** Clave conocida y DEBUG activo por defecto.

**Impacto:** Fuga de código/rutas si el servidor se expone; firma forjable de mensajes/tokens futuros.

**Solución recomendada:** Default `DEBUG=False`; fallar al arrancar si `SECRET_KEY` es el placeholder; generar clave aleatoria por entorno.

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Medio

### P13 — Auditoría sin paginación

**Severidad:** MEDIO  
**Categoría:** Rendimiento  
**Ubicación:** `audit/views.py:60-67`, `templates/audit/log_list.html:49`

**Evidencia:** La vista pasa el queryset completo al template. `{{ logs|length }}` fuerza evaluación total; luego la tabla itera el mismo queryset.

**Problema:** Carga y renderiza todas las filas de auditoría.

**Impacto:** Degradación lineal de memoria y tiempo con el crecimiento de la tabla.

**Comportamiento actual:** Cada visita a `/audit/` evalúa todo el queryset.

**Comportamiento esperado después de optimizar:** Paginar con `Paginator` y usar `paginator.count`.

**Solución recomendada:** Agregar paginación y eliminar `|length` sobre queryset.

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Bajo

### P14 — Generación PDF + inferencia ML síncronas en request

**Severidad:** MEDIO  
**Categoría:** Rendimiento  
**Ubicación:** `reports/views.py:233-237`, `reports/services.py:523-576`

**Evidencia:** `generate_report_file` ejecuta `predict_cognitive_result` y `build_pdf_bytes` dentro del POST de aprobación.

**Problema:** El request HTTP queda bloqueado durante inferencia y construcción manual del PDF.

**Impacto:** Timeouts e interfaz bloqueada; errores de PDF interrumpen la transacción.

**Comportamiento actual:** Aprobación y generación son atómicas en el mismo request.

**Comportamiento esperado después de optimizar:** Aprobación marca `GENERATING`; un worker genera el PDF asíncronamente; el usuario descarga cuando esté listo.

**Solución recomendada:** Desacoplar con thread/worker y estados `GENERATING`/`GENERATED`.

**Complejidad estimada:** Alta  
**Riesgo de regresión:** Alto

### P15 — TOCTOU en asociación de sesión

**Severidad:** MEDIO  
**Categoría:** Datos / Concurrencia  
**Ubicación:** `clinical_sessions/services/specialist_session_service.py:63-85`

**Evidencia:** Se consulta `existing` y luego se hace `update_or_create` sin bloqueo ni transacción que garantice atomicidad en SQLite.

**Problema:** Dos confirmaciones concurrentes pueden asignar la misma sesión a distintos especialistas.

**Impacto:** Propiedad incorrecta de sesión clínica.

**Solución recomendada:** Imponer unicidad de `session_id` y manejar `IntegrityError`; usar `select_for_update` (preparar para PostgreSQL) o update condicional.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P16 — Unique parcial permite duplicados huérfanos

**Severidad:** MEDIO  
**Categoría:** Datos  
**Ubicación:** `reports/models.py:45-53`

**Evidencia:** `UniqueConstraint(fields=["session_id", "requested_by"], condition=...)` incluye `requested_by`. SQLite trata NULLs como distintos. Validación con script temporal: se permitieron dos filas con mismo `session_id` y `requested_by=NULL`.

**Problema:** No se deduplican informes huérfanos a nivel de base de datos.

**Impacto:** Informes clínicos duplicados en flujo administrativo concurrente.

**Solución recomendada:** Agregar constraint parcial adicional para `requested_by IS NULL` o serializar el flujo huérfano.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P17 — `cache_session_metrics` escribe N veces por listado

**Severidad:** MEDIO  
**Categoría:** Rendimiento / Datos  
**Ubicación:** `clinical_sessions/views.py:94-95`

**Evidencia:** `SessionListView` itera sesiones completadas y llama `cache_session_metrics`, que ejecuta un UPDATE por sesión.

**Problema:** N escrituras en SQLite por cada GET del listado, aunque los datos no cambien.

**Impacto:** Contención de base de datos y latencia del listado.

**Comportamiento actual:** Cada visita al listado genera un UPDATE por sesión.

**Comportamiento esperado después de optimizar:** Escribir solo si los datos cambiaron, o sincronizar fuera del request.

**Solución recomendada:** Comparar hash/timestamp antes de actualizar; mover sincronización a tarea de fondo.

**Complejidad estimada:** Media  
**Riesgo de regresión:** Medio

### P18 — `RuntimeError` no capturado en updater

**Severidad:** MEDIO  
**Categoría:** Estabilidad  
**Ubicación:** `updater/views.py:30`, `updater/jobs.py:42-46`

**Evidencia:** `create_job()` lanza `RuntimeError` si el slot está ocupado; `UpdateRunView.post` no lo captura.

**Problema:** HTTP 500 ante una condición de concurrencia normal.

**Impacto:** Mala experiencia de usuario y posible pérdida de estado.

**Solución recomendada:** Capturar la excepción y devolver `409 Conflict` o `202 Accepted` con estado del job activo.

**Complejidad estimada:** Baja  
**Riesgo de regresión:** Bajo

### P19–P34 — Arquitectura, configuración, rendimiento y estabilidad

Los hallazgos P19–P34 corresponden a las ubicaciones e impactos indicados en la tabla priorizada: acceso directo al ORM desde vistas, acoplamiento de Cognito en forms, ubicación de `RoleRequiredMixin`, ausencia de logging, uso de `runserver`, dependencia `pywebview` sin pin, fixture `FAKE_SESSIONS`, elevación del instalador, proveedor local no utilizado, falta de `STATIC_ROOT`, cabeceras de seguridad, dependencias de desarrollo en runtime, checks síncronos del updater, materialización de exports, jobs en memoria y duplicación del ordenamiento de métricas. Las soluciones recomendadas son extraer lógica a servicios, endurecer configuración y despliegue, paginar/cachear/persistir donde corresponda y unificar helpers, con las complejidades y riesgos consignados en la tabla.

---

## Hallazgos descartados tras revisión cruzada

- **`accounts/tests.py` sombreado por `accounts/tests/`**: falso positivo. No existe `accounts/tests/__init__.py`; `python manage.py test accounts` ejecutó 80 tests correctamente.
- **JWT decodificado sin firma**: mitigado por diseño; el token nunca se acepta del cliente.
- **`np.load(..., allow_pickle=True)`**: no explotable en el flujo actual; artefactos son locales.
- **`/admin/` habilitado**: impacto limitado porque no hay modelos de negocio registrados.
- **Documentación ML "16 vs 12 columnas"**: desactualizada pero no defecto funcional; runtime y artefactos son coherentes.
- **Código muerto/arquitectónico menor**: templates huérfanos, boilerplate repetido, scripts heredados — se consideran deuda técnica de bajo impacto y no se incluyen como problemas prioritarios.

---

## Plan de mejoras

### Fase 1 — Problemas críticos y de seguridad (antes que cualquier otra cosa)

**Objetivo:** eliminar vectores de ataque graves y corregir el empaquetado.

1. **P1 — Autenticar/Autorizar endpoints del updater**
   - Archivos: `updater/views.py`, `updater/urls.py`, `static/updater/updater.js`
   - Orden: mover `RoleRequiredMixin` a `accounts` o módulo compartido; aplicarlo a `/updater/run/`; agregar token de sesión webview a `/updater/check/` y `/updater/progress/`.
   - Verificación: tests con `Client()` anónimo devuelven 302/403; usuario ADMIN puede ejecutar.

2. **P2 — Preservar `.env` en instalación silenciosa `/S`**
   - Archivos: `installer/neuroflex.nsi`
   - Orden: detectar modo silencioso; copiar `.env` existente o exigir parámetros `/D`.
   - Verificación: compilar NSIS y ejecutar `/S`; comprobar que `.env` conserva valores.

3. **P3 — Crear o corregir pipeline de release**
   - Archivos: `.github/workflows/release.yml` (nuevo) o `docs/updater-readme.md`
   - Orden: decidir si se automatiza o se documenta el manual; implementar.
   - Verificación: publicar un release de prueba y comprobar que `latest.json` y SHA256 son correctos.

4. **P5 — Eliminar XSS en `active_sessions.js`**
   - Archivos: `static/js/active_sessions.js`
   - Orden: reemplazar `innerHTML` por `createElement`/`textContent`.
   - Verificación: test con datos que contengan `<script>`; no debe ejecutarse.

5. **P6 — Sanitizar `next` en reports**
   - Archivos: `reports/views.py`
   - Orden: usar `url_has_allowed_host_and_scheme`.
   - Verificación: redirección a URL externa devuelve 400 o usa fallback seguro.

6. **P12 — Endurecer defaults de settings**
   - Archivos: `config/settings.py`, `neuroflex_launcher.py`, `.env.example`
   - Orden: `DEBUG=False` por defecto; fallar si `SECRET_KEY` es placeholder; generar clave en primer arranque.
   - Verificación: arranque sin `.env` muestra error claro; launcher genera clave.

### Fase 2 — Bugs y estabilidad

**Objetivo:** corregir comportamientos incorrectos y condiciones de carrera.

1. **P16 — Constraint única para informes huérfanos**
   - Archivos: `reports/models.py`, migración
   - Verificación: script SQLite confirma que duplicados con NULL ya no son posibles.

2. **P15 — TOCTOU en asociación de sesión**
   - Archivos: `clinical_sessions/models.py`, `specialist_session_service.py`
   - Verificación: tests de concurrencia simulada.

3. **P7 — Propagar borrado a Cognito**
   - Archivos: `accounts/views.py`, `accounts/services.py`
   - Orden: desactivar en Cognito primero; luego borrar local; excluir del sync.
   - Verificación: usuario borrado no puede volver a loguearse.

4. **P8 — Alinear sesión Django con tokens Cognito**
   - Archivos: `config/settings.py`, `accounts/views.py`
   - Orden: configurar expiración, `SESSION_EXPIRE_AT_BROWSER_CLOSE`, renovación de tokens.
   - Verificación: tras expirar token, el usuario es redirigido a login.

5. **P18 — Capturar `RuntimeError` en updater**
   - Archivos: `updater/views.py`, `updater/jobs.py`
   - Verificación: segundo POST concurrente devuelve 409/202, no 500.

### Fase 3 — Rendimiento

**Objetivo:** optimizar puntos con evidencia de degradación.

1. **P13 — Paginar auditoría**
   - Archivos: `audit/views.py`, `templates/audit/log_list.html`
   - Verificación: lista con 1000+ registros carga en <1 s.

2. **P14 — Generación asíncrona de PDF**
   - Archivos: `reports/views.py`, `reports/services.py`, `reports/models.py`
   - Orden: aprobación marca `GENERATING`; worker genera PDF; polling de estado.
   - Verificación: aprobación responde rápido; PDF aparece en estado `GENERATED`.

3. **P17 — Evitar N escrituras en listado de sesiones**
   - Archivos: `clinical_sessions/views.py`, `specialist_session_service.py`
   - Verificación: SQL log muestra 0-1 UPDATEs por GET.

4. **P31 — Cachear check de updater**
   - Archivos: `updater/services.py`, `updater/views.py`
   - Verificación: múltiples cargas de página no repiten llamadas a GitHub.

### Fase 4 — Arquitectura y mantenibilidad

**Objetivo:** reducir deuda técnica que dificulta futuros cambios.

1. Mover la orquestación de informes a servicios (P4).
2. Hacer que las vistas consuman servicios/managers (P19).
3. Extraer autenticación Cognito del form (P20).
4. Mover `RoleRequiredMixin` a `accounts` o módulo compartido (P21).
5. Decidir el futuro de `LocalSessionProvider` y actualizar la documentación (P27).
6. Unificar el ordenamiento de métricas (P34).

### Fase 5 — Mejoras opcionales

1. Fortalecer la cadena de confianza del updater con firma, versiones y almacenamiento seguro (P9–P11).
2. Configurar logging, evaluar WSGI embebido, fijar dependencias y generar lockfile (P22–P24).
3. Definir `STATIC_ROOT` y cabeceras de seguridad (P28–P29).
4. Separar dependencias de desarrollo y persistir jobs del updater (P30, P33).

---

## Conclusión

La aplicación cumple su propósito funcional y tiene controles de autorización sólidos, pero acumula riesgos concentrados en el actualizador automático, el empaquetado y la deuda técnica estructural. La prioridad inmediata es endurecer el updater y corregir el instalador silencioso, ya que ambos pueden dejar la aplicación inoperativa o comprometer el equipo del usuario. Las mejoras de arquitectura y rendimiento pueden abordarse de forma incremental sin alterar el comportamiento actual del sistema.
