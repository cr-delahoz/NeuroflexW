# NeuroFlex Dashboard

Aplicación web Django para administrar usuarios, visualizar sesiones clínicas de NeuroFlex VR, ejecutar inferencia de Machine Learning, gestionar informes PDF y mantener el sistema actualizado. Incluye retroalimentación visual de carga en toda la interfaz y un updater interno con barra de progreso.

---

## Características principales

- **Roles ADMIN y SPECIALIST** — administración de usuarios, dashboards diferenciados y control de acceso.
- **Sesiones clínicas** — visualización y detalle de sesiones desde JSON locales (reemplazable por API REST).
- **Machine Learning** — modelo ONNX de tres clases (`bajo`, `medio`, `alto`) para estimar bandas de desempeño; se muestra como resultado provisional, no diagnóstico. El modelo requiere las métricas de la sesión y la mano dominante del paciente.
- **Informes PDF** — solicitud, aprobación, rechazo y generación de informes clínicos.
- **Auditoría** — registro de eventos con exportación CSV y PDF.
- **Retroalimentación de carga** — spinners en botones, paginación y acciones mediante Tailwind + JS vanilla (`static/js/ui-feedback.js`).
- **Updater interno** — barra de progreso con polling a `/updater/progress/<job_id>/`, ejecución de batch sin consola Windows, metadatos vía `latest.json`.
- **Instalador Windows** — build con PyInstaller + NSIS.

---

## Dependencias del proyecto

### Runtime

| Dependencia | Version | Instalacion                                                    |
| ----------- | ------- | -------------------------------------------------------------- |
| Python      | >= 3.12 | [python.org](https://python.org)                               |
| Django      | 6.0.x   | `pip install django`                                           |
| node / npm  | >= 20   | [nodejs.org](https://nodejs.org) — solo para build de Tailwind |

### Paquetes Python

```bash
pip install -r requirements.txt
```

### PyInstaller (build del .exe)

```bash
pip install pyinstaller
```

### NSIS (build del instalador)

```
choco install nsis
```

o descargar desde [nsis.sourceforge.io](https://nsis.sourceforge.io/).

Instalacion estandar en `C:\Program Files (x86)\NSIS\makensis.exe`.

---

## Desarrollo local

```bash
# 1. Entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 2. Dependencias
pip install -r requirements.txt

# 3. Variables de entorno
copy .env.example .env   # editar segun corresponda

# 4. Tailwind CSS
npm install
npm run tailwind:build   # o tailwind:watch para desarrollo

# 5. Migraciones y servidor
python manage.py migrate
python manage.py runserver
```

---

## Build del instalador

El script `installer/build_release.ps1` automatiza todo el proceso.

### Requisitos

- Python + dependencias + PyInstaller instalados
- NSIS 3.x instalado en `C:\Program Files (x86)\NSIS\`
- Tailwind compilado (`npm run tailwind:build`)
- El proyecto debe estar en un estado funcional (`python manage.py check` sin errores)

### Uso

```powershell
cd installer
.\build_release.ps1 -Version "X.X.X"
```

### Proceso

1. **PyInstaller** — compila `neuroflex_launcher.py` y todo Django en un solo `.exe`
2. **NSIS** — genera el instalador con interfaz MUI2 (gradiente, logo, pagina de configuracion)
3. **SHA256** — calcula el hash del instalador para verificar integridad
4. **latest.json** — genera el archivo de metadatos que consume el actualizador interno

### Archivos generados

```
installer/upload-to-release/
+-- NeuroFlex-Setup-X.X.X.exe    - Instalador
+-- latest.json                  - Metadatos para el updater
```

### Subir a GitHub Release

1. Crear el tag de version: `git tag -a vX.X.X -m "mensaje"`
2. Pushear el tag de version: `git push origin vX.X.X`
3. Mover y pushear el tag `latest` al mismo commit (necesario para el updater):
   ```bash
   git tag -f latest vX.X.X
   git push -f origin latest
   ```
4. En GitHub: **Releases > Draft a new release** — seleccionar el tag `vX.X.X`
5. Subir `NeuroFlex-Setup-X.X.X.exe` y `latest.json`
6. Marcar **"Set as the latest release"**
7. Publicar el release

---

## Assets del instalador

Los BMP e ICO del wizard MUI2 se generan con Pillow:

```bash
pip install pillow
python installer/assets/build_assets.py
```

Salida: `installer/assets/{welcome,un-welcome,header}.bmp` + `neuroflex.ico`

No es necesario ejecutarlo manualmente a menos que se modifique el diseno.

---

## Tests

Ejecutar las suites relevantes según el área modificada:

```bash
# Tests del updater (servicios, vistas, jobs, templates)
python manage.py test updater.tests -v 2

# Tests de retroalimentación de carga
python manage.py test dashboard.tests.test_loading_feedback_templates -v 2

# Tests del resto de aplicaciones
python manage.py test accounts clinical_sessions reports audit -v 2
```

Después de cada cambio ejecutar también:

```bash
python manage.py check
```

---

## Reconciliación de usuarios

El comando `reconcile_users` sincroniza usuarios locales con Cognito y detecta diferencias entre ambos sistemas.

```bash
python manage.py reconcile_users --token <cognito_id_token>
python manage.py reconcile_users --dry-run --token <cognito_id_token>
python manage.py reconcile_users --resolve=report --token <cognito_id_token>
python manage.py reconcile_users --skip-orphans --token <cognito_id_token>
```

Opciones:

- `--token`: token ID de Cognito de un administrador.
- `--dry-run`: muestra los cambios sin aplicarlos.
- `--resolve`: `update` (predeterminado) o `report`.
- `--skip-orphans`: oculta usuarios locales que no existen en Cognito.

El token puede obtenerse con AWS CLI mediante `initiate-auth` o desde la sesión del navegador. Es temporal y debe pasarse explícitamente con `--token`.
