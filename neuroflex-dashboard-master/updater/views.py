import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from django.http import JsonResponse
from django.views import View

from audit.models import AuditLog
from audit.services import get_client_ip, log_event
from .jobs import cleanup_job, create_job, get_job, update_job
from .services import UpdaterError, download_installer_with_progress, has_update_available

logger = logging.getLogger(__name__)
SAFE_ERROR = "No se pudo descargar o preparar la actualización. Inténtalo nuevamente."


class UpdateCheckView(View):
    def get(self, request, *args, **kwargs):
        info = has_update_available()
        return JsonResponse({"has_update": bool(info), "version": info["version"] if info else "", "changelog": info["changelog"] if info else "", "url": info["url"] if info else "", "sha256": info["sha256"] if info else ""})


class UpdateRunView(View):
    def post(self, request, *args, **kwargs):
        job, reused = create_job()
        if reused:
            return JsonResponse({**job, "reused": True}, status=202)
        try:
            info = has_update_available()
            if info is None:
                update_job(job["job_id"], "error", None, "No hay actualización disponible.")
                cleanup_job(job["job_id"])
                return JsonResponse({"status": "error", "message": "No hay actualización disponible."}, status=400)
            update_info = {key: info[key] for key in ("version", "url", "filename", "sha256")}
        except Exception:
            logger.exception("Error al obtener información de actualización")
            update_job(job["job_id"], "error", None, SAFE_ERROR)
            cleanup_job(job["job_id"])
            return JsonResponse({"status": "error", "message": SAFE_ERROR}, status=500)
        actor = request.user if request.user.is_authenticated else None
        ip_address = get_client_ip(request)
        thread = threading.Thread(target=self._run_update, args=(job["job_id"], update_info, actor, ip_address), daemon=True)
        thread.start()
        return JsonResponse({**job, "reused": False}, status=202)

    @staticmethod
    def _run_update(job_id, info, actor, ip_address):
        installer = None
        bat_path = None
        try:
            update_job(job_id, "downloading", None, "Descargando instalador…")
            installer = download_installer_with_progress(job_id, lambda progress, message: update_job(job_id, "downloading", progress, message), info["url"], info["sha256"], filename=info["filename"] or None)
            update_job(job_id, "downloading", 100, "Preparando instalación…")
            # Renombrar a nombre fijo para evitar inyección de comandos en el batch
            installer_dir = installer.parent
            safe_installer = installer_dir / "installer.exe"
            safe_installer.unlink(missing_ok=True)
            installer.rename(safe_installer)
            installer = safe_installer
            bat_path = _create_update_bat(installer)
            subprocess.Popen(["cmd", "/c", str(bat_path)], creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            try:
                log_event(actor=actor, action="actualizacion_aplicada", resource_type="application", resource_id="", result=AuditLog.Result.SUCCESS, ip_address=ip_address, metadata={"new_version": info["version"]})
            except Exception:
                logger.error("No se pudo registrar el evento de auditoría para la actualización", exc_info=True)
            update_job(job_id, "ready", 100, "La aplicación se cerrará para completar la instalación.")
            _delayed_exit()
            update_job(job_id, "done", 100, "Actualización entregada al instalador.")
        except (UpdaterError, OSError, subprocess.SubprocessError):
            current = get_job(job_id)
            last_pct = current["percentage"] if current else None
            update_job(job_id, "error", last_pct, SAFE_ERROR)
            _cleanup_temp_files(installer, bat_path)
        except Exception:
            logger.exception("Fallo inesperado preparando la actualización")
            current = get_job(job_id)
            last_pct = current["percentage"] if current else None
            update_job(job_id, "error", last_pct, SAFE_ERROR)
            _cleanup_temp_files(installer, bat_path)
        finally:
            cleanup_job(job_id)


class UpdateProgressView(View):
    def get(self, request, job_id, *args, **kwargs):
        job = get_job(job_id)
        if job is None:
            return JsonResponse({"status": "error", "message": "Trabajo de actualización no encontrado."}, status=404)
        return JsonResponse(job)


def _delayed_exit(delay=2.0):
    threading.Thread(target=lambda: (time.sleep(delay), os._exit(0)), daemon=True).start()


def _create_update_bat(installer_path):
    bat_path = Path(tempfile.gettempdir()) / "neuroflex_update.bat"
    install_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    exe_path = install_dir / "neuroflex.exe"
    bat_path.write_text(f'''@echo off
set LOG=%LOCALAPPDATA%\\NeuroFlex\\update.log
echo Actualizacion de NeuroFlex - %DATE% %TIME% > "%LOG%"
:wait
tasklist /fi "imagename eq neuroflex.exe" | find "neuroflex.exe" >nul 2>&1
if %errorlevel% equ 0 (timeout /t 1 /nobreak >nul & goto wait)
echo [%TIME%] Instalando actualizacion... >> "%LOG%"
"{installer_path}" /S
if %errorlevel% neq 0 (
  echo [%TIME%] ERROR: instalador %errorlevel% >> "%LOG%"
  del "%%~f0"
  exit /b 1
)
echo [%TIME%] Instalacion completada. >> "%LOG%"
start "" "{exe_path}"
del "{installer_path}"
del "%%~f0"
''', encoding="utf-8")
    return bat_path


def _cleanup_temp_files(installer_path, bat_path):
    if installer_path and Path(installer_path).exists():
        try:
            Path(installer_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("No se pudo eliminar el instalador temporal: %s", installer_path)
    if bat_path and Path(bat_path).exists():
        try:
            Path(bat_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("No se pudo eliminar el batch temporal: %s", bat_path)
