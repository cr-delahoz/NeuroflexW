# Backlog de NeuroFlex

Fecha de revisión: **5 de noviembre de 2026**.

Backlog inicial basado en el código de esta copia, su documentación y las comprobaciones indicadas al final. Incluye los cambios locales que ya existían antes de esta revisión. Las tareas son propuestas; crear este documento no implica que estén implementadas ni aprobadas para una entrega. Responsables y fechas quedan por asignar.

## Alcance y prioridades

El proyecto ya tiene autenticación y roles, integración con API/Cognito, sesiones, clasificación ML provisional, informes PDF, auditoría, términos, captura offline/LAN, sincronización e instalador Windows. El trabajo inicial se concentra en consolidar estos flujos.

- **P1 — Alta:** resolver antes de la siguiente entrega a usuarios.
- **P2 — Media:** siguiente bloque de trabajo, después de estabilizar P1.
- **P3 — Baja:** mejora posterior a los flujos principales.

Tamaño relativo: **S** = cambio acotado; **M** = varios componentes; **L** = integración o validación de varios flujos. No son compromisos de duración. Estado inicial: **Pendiente**, salvo las dependencias indicadas.

La evidencia se distingue entre **prueba ejecutada**, **revisión de código** y **mejora propuesta**. Un hallazgo por revisión de código no equivale a una explotación reproducida.

## Lista priorizada

| ID | Prioridad | Tarea | Tamaño | Dependencia |
| --- | --- | --- | --- | --- |
| NF-001 | P1 | Recuperar una ejecución de pruebas consistente | S | Ninguna |
| NF-002 | P1 | Alinear permisos de informes y sesiones sin especialista | M | Definir tratamiento funcional de sesiones huérfanas |
| NF-003 | P1 | Restringir quién puede ejecutar el actualizador | M | Definir rol autorizado para actualizar |
| NF-004 | P1 | Renderizar datos de sesiones sin interpretar HTML externo | S | Ninguna |
| NF-005 | P1 | Validar la redirección posterior a solicitar un informe | S | Ninguna |
| NF-006 | P1 | Evitar que una eliminación local se presente como baja completa | M | Baja remota definitiva depende de permisos/API AWS |
| NF-007 | P1 | Impedir cambios de dueño por confirmaciones concurrentes | M | Ninguna |
| NF-008 | P2 | Evitar informes activos duplicados en sesiones huérfanas | M | NF-002 |
| NF-009 | P2 | Diferenciar errores de API y detectar paginación incompleta | M | Contrato confirmado de la API |
| NF-010 | P2 | Separar las sesiones de demostración del uso normal | S | Ninguna |
| NF-011 | P2 | Reducir escrituras de métricas y paginar auditoría | M | Ninguna |
| NF-012 | P2 | Incorporar verificaciones obligatorias al build de Windows | M | NF-001 y herramientas de build |
| NF-013 | P2 | Documentar y comprobar respaldo y restauración | M | Entorno de prueba aislado |
| NF-014 | P2 | Unificar el acceso a sesiones y actualizar la documentación | L | NF-009 |
| NF-015 | P2 | Validar el flujo completo online y offline con datos sintéticos | L | NF-002, NF-007, NF-009 y entorno de prueba |
| NF-016 | P3 | Preparar el servidor embebido y sus logs para uso sostenido | M | NF-015 como regresión |

## Tareas y criterios de aceptación

### NF-001 — Recuperar una ejecución de pruebas consistente

**Evidencia: prueba ejecutada.** La suite Django descubre 717 pruebas y termina con un fallo: `ClinicalSessionViewTests.test_session_detail_shows_automated_result_without_hand_metadata`, en `clinical_sessions/tests/test_views.py`. Busca el texto de probabilidad técnica que `templates/clinical_sessions/session_detail.html` ya no muestra. Las dos suites JavaScript no arrancan por ausencia de `jsdom`; `npm` tampoco está disponible en el PATH de esta sesión.

**Aceptación:**

- Alinear la expectativa de la prueba con la presentación aprobada del resultado, conservando la clasificación provisional y el funcionamiento sin mano dominante. No reintroducir información técnica solo para satisfacer una aserción antigua.
- La suite Django completa pasa con la configuración de pruebas.
- Documentar la preparación de Node/npm y ejecutar las suites JavaScript con sus dependencias declaradas. Distinguir fallos de entorno de defectos funcionales.

### NF-002 — Alinear permisos de informes y sesiones sin especialista

**Evidencia: revisión de código.** `AGENTS.md` prohíbe al ADMIN ver sesiones/resultados clínicos y descargar informes. Sin embargo, `AdminReportDownloadView`, `AdminGenerateOrphanReportView` y la vista de sesiones sin especialista ofrecen excepciones. Hay pruebas que esperan que el administrador descargue informes huérfanos.

**Aceptación:**

- Documentar una matriz única de permisos para ADMIN y SPECIALIST, incluyendo eliminación del especialista, sesiones sin dueño e informes ya emitidos.
- Aplicar la restricción vigente de `AGENTS.md`; cualquier excepción requiere una decisión funcional explícita y la actualización de esa regla.
- Probar URLs directas y botones: el ADMIN puede aprobar/rechazar sin obtener contenido clínico; cada especialista accede únicamente a sus recursos autorizados.

### NF-003 — Restringir quién puede ejecutar el actualizador

**Evidencia: revisión de código.** Las vistas de `updater/views.py` heredan de `View` sin exigir autenticación ni rol. La ejecución descarga un instalador, lanza un batch y cierra la aplicación. El middleware limita la UI a localhost, pero no verifica la identidad del usuario local. El batch usa un nombre temporal fijo.

**Aceptación:**

- Establecer el rol autorizado y exigirlo en el inicio de actualización; definir también acceso a consulta y progreso, incluyendo la pantalla de login.
- Los intentos no autorizados no crean trabajos, descargan archivos, ejecutan procesos ni cierran la aplicación; mantener CSRF en la operación web.
- Usar un directorio temporal por trabajo y comprobar checksum, limpieza y reutilización del trabajo activo con procesos simulados en las pruebas.

### NF-004 — Renderizar datos de sesiones sin interpretar HTML externo

**Evidencia: revisión de código.** `static/js/active_sessions.js` concatena `session_id`, `display_code` y `vr_user_email` en `innerHTML`.

**Aceptación:**

- Construir los valores externos como texto usando APIs de DOM seguras.
- Valores con etiquetas, comillas o manejadores de eventos se muestran literalmente y no ejecutan código.
- Conservar la actualización automática, el estado vacío y el formato de fechas; cubrir el comportamiento con una prueba JavaScript.

### NF-005 — Validar la redirección posterior a solicitar un informe

**Evidencia: revisión de código.** `ReportRequestCreateView` utiliza `redirect(next_url)` con un valor recibido por POST en `reports/views.py`.

**Aceptación:**

- Aceptar únicamente destinos internos autorizados mediante validación de host/esquema o una lista de rutas.
- Destinos externos, URLs con `//` y valores malformados usan una ruta interna de respaldo.
- Conservar el retorno válido al detalle o listado y probar ambos casos.

### NF-006 — Evitar que una eliminación local se presente como baja completa

**Evidencia: revisión de código.** `UserDeleteView` elimina la fila local y muestra éxito, pero su TODO indica que no elimina el registro Cognito. El comentario señala una limitación de credenciales IAM en AWS Academy; no se verificó el estado actual de esa cuenta AWS.

**Aceptación:**

- Definir la diferencia entre desactivación, eliminación local y revocación remota. El mensaje de la UI informa exactamente qué se completó.
- Evitar que el siguiente login o la reconciliación restaure acceso a una cuenta que se pretendía dar de baja, usando el mecanismo autorizado disponible.
- Si la baja remota requiere permisos externos, dejar un procedimiento manual comprobable, estado pendiente visible y auditoría sin credenciales.
- Probar reingreso, reconciliación y conservación de referencias históricas después de la baja.

**Dependencia externa:** verificar permisos o endpoint de administración antes de implementar una baja remota definitiva.

### NF-007 — Impedir cambios de dueño por confirmaciones concurrentes

**Evidencia: revisión de código.** `confirm_and_associate_session()` consulta al propietario y después llama a `update_or_create()` con el nuevo especialista en `defaults`. `session_id` ya es único: evita filas duplicadas, pero la comprobación previa no hace atómica la decisión de conservar al dueño.

**Aceptación:**

- Dos confirmaciones concurrentes para especialistas distintos conservan un único propietario sin sobrescritura.
- Repetir la confirmación por el dueño es idempotente; otro usuario recibe un error controlado.
- Cubrir creación concurrente y fila existente con SQLite, sin mantener una transacción abierta durante llamadas HTTP.

### NF-008 — Evitar informes activos duplicados en sesiones huérfanas

**Evidencia: revisión de código.** La restricción de `ReportRequest` combina `session_id` y `requested_by`; este último admite NULL. La comprobación previa de existencia en el flujo huérfano no garantiza exclusión entre solicitudes simultáneas.

**Aceptación:**

- Definir la unicidad aplicable después de NF-002 y garantizarla en base de datos cuando corresponda.
- Detectar y resolver duplicados existentes antes de añadir una migración restrictiva.
- Una operación concurrente no genera dos informes activos; una solicitud rechazada permite el reintento definido por negocio.

### NF-009 — Diferenciar errores de API y detectar paginación incompleta

**Evidencia: revisión de código.** `confirm_display_code()` transforma cualquier `NeuroflexApiResponseError` en código inválido aunque la excepción ya contiene `status_code`. El listado asume el parámetro `cursor` y termina tras veinte páginas sin comunicar que podría faltar información.

**Aceptación:**

- Distinguir código inválido, autorización expirada/denegada, límite de peticiones y error del servidor; mostrar mensajes y recuperación adecuados.
- Confirmar el contrato de paginación, probar una segunda página y detectar cursores repetidos o límite alcanzado sin presentar el resultado como completo.
- Validar el formato mínimo de las respuestas y probar fallos de transporte con mocks, sin depender de una API real para la suite unitaria.

### NF-010 — Separar las sesiones de demostración del uso normal

**Evidencia: revisión de código.** `external_session_client.py` devuelve una lista fija si `FAKE_SESSIONS=1`, sin filtrar por el especialista solicitado.

**Aceptación:**

- Trasladar los fixtures a pruebas o a un modo demo explícito, aislado y visible.
- Una instalación normal no sustituye datos reales por demostraciones debido a una variable accidental.
- Probar que especialistas distintos no reciben sesiones compartidas por esta vía.

### NF-011 — Reducir escrituras de métricas y paginar auditoría

**Evidencia: revisión de código.** El listado de sesiones llama a `cache_session_metrics()` para cada sesión completada; la función actualiza también cuando los datos son iguales. `AuditLogListView` entrega el queryset completo al template.

**Aceptación:**

- Reabrir una lista sin cambios no produce escrituras de métricas; las métricas nuevas se conservan correctamente.
- Paginar auditoría manteniendo filtros y orden; la exportación abarca el resultado filtrado completo.
- Medir consultas y tiempos con un conjunto sintético representativo antes y después, y registrar los resultados.

### NF-012 — Incorporar verificaciones obligatorias al build de Windows

**Evidencia: revisión de código.** `installer/build_release.ps1` compila, empaqueta y genera el SHA256, pero no ejecuta los checks, pruebas ni `tools/verify_desktop_build.py`. Este verificador ya existe como cambio local y está mencionado en el README. El instalador ya contiene lógica para preservar valores de configuración durante `/S`.

**Aceptación:**

- El proceso de entrega falla antes de empaquetar/publicar si fallan las verificaciones acordadas; incluir el verificador del ejecutable y conservar su reporte.
- Comprobar instalación limpia y actualización silenciosa con configuración, base de datos e informes sintéticos; verificar qué variables deben preservarse, incluido el modo offline/LAN.
- Verificar correspondencia entre versión, ejecutable, `latest.json` y SHA256, y exclusión de datos privados.
- Documentar la versión de Python realmente soportada: el README indica 3.12 y el entorno usado en esta revisión ejecutó Python 3.13.

### NF-013 — Documentar y comprobar respaldo y restauración

**Evidencia: mejora propuesta.** Hay datos persistentes locales (`db.sqlite3`, informes privados, configuración y sesiones pendientes); no se encontró un procedimiento operativo de recuperación en la documentación revisada.

**Aceptación:**

- Definir qué respaldar y cómo obtener una copia consistente de SQLite y archivos relacionados.
- Documentar almacenamiento y acceso al respaldo, incluyendo configuración sensible y sesiones offline pendientes.
- Restaurar en una carpeta/instalación aislada con datos sintéticos y comprobar login, informes y pendientes de sincronización.

### NF-014 — Unificar el acceso a sesiones y actualizar la documentación

**Evidencia: revisión de código.** El README y `AGENTS.md` describen JSON locales como fuente actual y API como futura. Las vistas actuales ya usan el cliente externo; `SessionDataService` solo selecciona el proveedor local. Hay acceso directo al ORM y orquestación de informes en vistas.

**Aceptación:**

- Documentar las fuentes reales: API online, persistencia/caché local y captura offline, con sus responsabilidades.
- Hacer que las vistas consuman servicios con un contrato estable, manteniendo la compatibilidad local requerida por `AGENTS.md`.
- Extraer gradualmente la orquestación de informes y normalización de sesiones a servicios, conservando permisos, auditoría y contrato de inferencia.
- Probar equivalencia de los datos normalizados entre fuentes compatibles y actualizar README, diagramas e instrucciones del proyecto.

### NF-015 — Validar el flujo completo online y offline con datos sintéticos

**Evidencia: mejora propuesta apoyada en herramientas existentes.** Hay pruebas unitarias de offline, una colección Postman y un simulador Quest. `postman/README.md` distingue la confirmación por API de la confirmación que crea asociación y auditoría en Django. Eso no acredita por sí solo todo el recorrido de UI, ML, PDF y reconexión.

**Aceptación:**

- Online: términos → crear sesión VR → confirmar por código desde Django → enviar métricas → ver resultado provisional → solicitar/aprobar → descargar como especialista.
- Offline: emparejar dispositivo → capturar → desconectar/reconectar → sincronizar; verificar aislamiento por propietario y recuperación ante token expirado, reintento, duplicado y reinicio.
- Comprobar que un fallo no elimina sesiones pendientes; los éxitos y duplicados confirmados siguen la política de limpieza implementada.
- Registrar resultados reproducibles con datos sintéticos, sin exportar contraseñas ni tokens. Mantener el modelo congelado, sin exigir mano dominante ni presentar la clasificación como diagnóstico.

### NF-016 — Preparar el servidor embebido y sus logs para uso sostenido

**Evidencia: revisión de código y mejora propuesta.** El launcher usa `runserver` en `0.0.0.0` para UI local y API LAN. Ya existen logs del launcher, pero falta una política común de niveles, rotación y saneamiento. Los valores por defecto de Django permiten debug y hosts amplios; el instalador sí escribe `DJANGO_DEBUG=False`.

**Aceptación:**

- Evaluar un servidor WSGI embebido compatible con Windows y el instalador; conservar las barreras localhost y la API LAN autorizada.
- Mantener una configuración explícita por entorno y comprobar arranque, cierre, puerto ocupado y concurrencia básica.
- Definir logs con rotación y mensajes útiles, sin tokens, contraseñas, métricas completas ni datos clínicos. Validar los cambios con el recorrido NF-015.

## Orden sugerido de ejecución

1. **Estabilización y permisos:** NF-001 a NF-007. Resolver las decisiones de permisos al inicio; NF-004 y NF-005 pueden avanzar sin ellas.
2. **Datos y entrega:** NF-008 a NF-013, respetando sus dependencias.
3. **Consolidación:** NF-014 y NF-015; luego NF-016.

No se fijan fechas ni capacidad de sprint hasta acordar disponibilidad del equipo. Para seguimiento: **Pendiente → En curso → En revisión → Hecho**; usar **Bloqueado** únicamente con una dependencia concreta registrada.

Una tarea está hecha cuando cumple sus criterios, pasa `manage.py check` y las pruebas relacionadas, actualiza la documentación afectada y conserva los límites de acceso y del modelo establecidos para el proyecto.

## Verificación de esta revisión

- ` .venv\Scripts\python.exe manage.py check`: **sin problemas**.
- `.venv\Scripts\python.exe manage.py test --settings=config.test_settings --noinput`: **717 pruebas, 1 fallo**, duración reportada 48,492 s. Fallo detallado en NF-001.
- `npm test`: no ejecutable desde este PATH, porque `npm` no se reconoce.
- Alternativa directa con `node.exe --test static/js/tests/local_config.test.js static/js/tests/sidebar_toggle.test.js`: las dos suites no cargaron por falta de `jsdom`. No se considera un defecto funcional de la interfaz.
- No se realizó un build, instalación, prueba con visor ni validación manual completa de interfaz. No se ejecutó deliberadamente una prueba de integración contra AWS/Postman; algunos tests Django intentaron resolver el host ficticio `api.example.test`, lo que conviene aislar en NF-009.
- La auditoría del 12 de agosto de 2026 se usó como antecedente y se contrastó con el código. No se copiaron como pendientes la comparación de versiones del updater, la fijación de `pywebview` ni la preservación básica del `.env` en `/S`, porque ya hay implementación para esos puntos; queda su validación de entrega en NF-012.
- En esta revisión se añadió únicamente este documento. Se conservaron los cambios locales preexistentes.

## Fuera del alcance inicial

Docker, Kubernetes, Redis, Celery, PostgreSQL, microservicios y una API definitiva requieren una solicitud específica según `AGENTS.md`. La consulta anterior sobre Docker no se trata como autorización para implementarlo. Tampoco se incluye reentrenamiento ni validación clínica del modelo.
