import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from audit.models import AuditLog
from updater import jobs
from updater.services import UpdaterError
from updater.views import UpdateProgressView, UpdateRunView, _create_update_bat


_fake_installers = []


def _make_fake_installer():
    fd, path = tempfile.mkstemp(suffix=".exe")
    os.close(fd)
    _fake_installers.append(path)
    return Path(path)


UPDATE = {"version": "2.0.0", "url": "https://example.com/setup.exe", "filename": "setup.exe", "sha256": "abc"}
NativeThread = threading.Thread


class HeldThread:
    targets = []
    def __init__(self, target, args=(), daemon=False):
        self.target = lambda: target(*args)
        HeldThread.targets.append(self.target)
    def start(self): pass


class RealThread:
    threads = []
    def __init__(self, target, args=(), daemon=False):
        self.thread = NativeThread(target=target, args=args, daemon=daemon)
        RealThread.threads.append(self.thread)
    def start(self): self.thread.start()


class UpdateViewsTest(SimpleTestCase):
    def setUp(self):
        jobs.reset_jobs_for_tests(); HeldThread.targets = []; RealThread.threads = []; self.factory = RequestFactory()

    def tearDown(self):
        jobs.reset_jobs_for_tests()
        lst = list(_fake_installers)
        _fake_installers.clear()
        for p in lst:
            Path(p).unlink(missing_ok=True)

    def post(self):
        request = self.factory.post("/updater/run/"); request.user = AnonymousUser()
        return UpdateRunView.as_view()(request)

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    def test_second_post_reuses_held_active_job(self, _available):
        first = json.loads(self.post().content)
        second = json.loads(self.post().content)
        self.assertFalse(first["reused"]); self.assertTrue(second["reused"])
        self.assertEqual(first["job_id"], second["job_id"]); self.assertEqual(len(HeldThread.targets), 1)

    @patch("updater.views.threading.Thread", RealThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    @patch("updater.views.log_event")
    @patch("updater.views._delayed_exit")
    @patch("updater.views.subprocess.Popen")
    def test_second_post_reuses_job_during_download_and_preparation(self, _popen, _exit, _log, _available):
        downloading = threading.Event(); allow_download = threading.Event()
        preparing = threading.Event(); allow_preparation = threading.Event()

        def fake_download(*args, **kwargs):
            downloading.set(); allow_download.wait(timeout=1)
            return _make_fake_installer()

        def fake_batch(*args, **kwargs):
            preparing.set(); allow_preparation.wait(timeout=1)
            return Path("C:/temp/update.bat")

        with patch("updater.views.download_installer_with_progress", side_effect=fake_download), patch("updater.views._create_update_bat", side_effect=fake_batch):
            first = json.loads(self.post().content)
            self.assertTrue(downloading.wait(timeout=1))
            during_download = json.loads(self.post().content)
            self.assertTrue(during_download["reused"])
            self.assertEqual(during_download["job_id"], first["job_id"])
            allow_download.set()
            self.assertTrue(preparing.wait(timeout=1))
            during_preparation = json.loads(self.post().content)
            self.assertTrue(during_preparation["reused"])
            self.assertEqual(during_preparation["job_id"], first["job_id"])
            allow_preparation.set()
            RealThread.threads[0].join(timeout=1)

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    def test_progress_endpoint_returns_terminal_and_error_states(self, _available):
        job = json.loads(self.post().content)
        jobs.update_job(job["job_id"], "downloading", 50, "Descargando…")
        jobs.update_job(job["job_id"], "ready", 100, "Preparando instalación…")
        jobs.update_job(job["job_id"], "done", 100, "Actualización entregada al instalador.")
        request = self.factory.get(f'/updater/progress/{job["job_id"]}/')
        response = UpdateProgressView.as_view()(request, job_id=job["job_id"])
        self.assertEqual(response.status_code, 200); self.assertEqual(json.loads(response.content)["status"], "done")
        jobs.cleanup_job(job["job_id"])
        error_job, _ = jobs.create_job()
        jobs.update_job(error_job["job_id"], "downloading", 50, "Descargando…")
        jobs.update_job(error_job["job_id"], "error", None, "No se pudo completar la actualización.")
        error_request = self.factory.get(f'/updater/progress/{error_job["job_id"]}/')
        error_response = UpdateProgressView.as_view()(error_request, job_id=error_job["job_id"])
        self.assertEqual(error_response.status_code, 200); self.assertEqual(json.loads(error_response.content)["status"], "error")
        missing = UpdateProgressView.as_view()(self.factory.get("/updater/progress/missing/"), job_id="missing")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(json.loads(missing.content), {"status": "error", "message": "Trabajo de actualización no encontrado."})

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    @patch("updater.views.download_installer_with_progress", side_effect=UpdaterError("bad checksum"))
    def test_worker_records_safe_download_error(self, _download, _available):
        job = json.loads(self.post().content); HeldThread.targets[0]()
        state = jobs.get_job(job["job_id"])
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["message"], "No se pudo descargar o preparar la actualización. Inténtalo nuevamente.")

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    @patch("updater.views.log_event")
    @patch("updater.views._delayed_exit")
    @patch("updater.views.subprocess.Popen")
    @patch("updater.views._create_update_bat", return_value=Path("C:/temp/update.bat"))
    @patch("updater.views.download_installer_with_progress", side_effect=lambda *a, **kw: _make_fake_installer())
    def test_worker_launches_hidden_batch(self, _download, _bat, popen, delayed_exit, _log, _available):
        self.post(); HeldThread.targets[0]()
        self.assertEqual(popen.call_args.kwargs["creationflags"], __import__("subprocess").CREATE_NO_WINDOW)
        delayed_exit.assert_called_once()

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    @patch("updater.views._delayed_exit")
    @patch("updater.views.subprocess.Popen")
    @patch("updater.views._create_update_bat", return_value=Path("C:/temp/update.bat"))
    @patch("updater.views.download_installer_with_progress", side_effect=lambda *a, **kw: _make_fake_installer())
    def test_worker_logs_audit_on_success(self, _download, _bat, _popen, _exit, _available):
        with patch("updater.views.log_event") as mock_log:
            self.post()
            HeldThread.targets[0]()
            mock_log.assert_called_once_with(
                actor=None,
                action="actualizacion_aplicada",
                resource_type="application",
                resource_id="",
                result=AuditLog.Result.SUCCESS,
                ip_address="127.0.0.1",
                metadata={"new_version": "2.0.0"},
            )

    @patch("updater.views.threading.Thread", HeldThread)
    @patch("updater.views.has_update_available", return_value=UPDATE)
    @patch("updater.views.download_installer_with_progress", side_effect=UpdaterError("bad checksum"))
    def test_worker_does_not_log_audit_on_download_error(self, _download, _available):
        with patch("updater.views.log_event") as mock_log:
            self.post()
            HeldThread.targets[0]()
            mock_log.assert_not_called()


class CreateUpdateBatTest(SimpleTestCase):
    def test_batch_logs_failure_without_pause(self):
        bat_path = _create_update_bat(Path("C:/temp/setup.exe"))
        content = bat_path.read_text(encoding="utf-8")
        self.assertIn("update.log", content); self.assertIn("exit /b 1", content)
        self.assertNotIn("pause", content); self.assertNotIn("title ", content)
        bat_path.unlink(missing_ok=True)
