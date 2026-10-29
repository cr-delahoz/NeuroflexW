import threading
from unittest.mock import patch

from django.test import SimpleTestCase

from updater import jobs


class UpdateJobStoreTest(SimpleTestCase):
    def setUp(self):
        jobs.reset_jobs_for_tests()

    def tearDown(self):
        jobs.reset_jobs_for_tests()

    def test_creates_and_reads_pending_job(self):
        job, reused = jobs.create_job()
        self.assertFalse(reused)
        self.assertEqual(job["status"], "pending")
        self.assertIsNone(job["percentage"])
        self.assertEqual(jobs.get_job(job["job_id"]), job)

    def test_updates_download_progress(self):
        job, _ = jobs.create_job()
        updated = jobs.update_job(job["job_id"], "downloading", 50, "Descargando instalador…")
        self.assertEqual(updated["percentage"], 50)
        self.assertEqual(updated["status"], "downloading")
        jobs.cleanup_job(job["job_id"])

    def test_second_creator_reuses_active_job(self):
        first, reused = jobs.create_job()
        self.assertFalse(reused)
        second, reused = jobs.create_job()
        self.assertTrue(reused)
        self.assertEqual(second["job_id"], first["job_id"])
        jobs.cleanup_job(first["job_id"])

    def test_update_slot_is_exclusive_until_cleanup(self):
        first, _ = jobs.create_job()
        entered = threading.Event()
        release = threading.Event()

        def hold_slot():
            entered.set()
            release.wait(timeout=1)
            jobs.cleanup_job(first["job_id"])

        thread = threading.Thread(target=hold_slot)
        thread.start()
        entered.wait(timeout=1)
        self.assertTrue(jobs.is_update_running())
        second, reused = jobs.create_job()
        self.assertTrue(reused)
        self.assertEqual(second["job_id"], first["job_id"])
        release.set()
        thread.join(timeout=1)

    def test_cleanup_removes_expired_terminal_job(self):
        job, _ = jobs.create_job()
        jobs.update_job(job["job_id"], "downloading", 50, "Descargando…")
        jobs.update_job(job["job_id"], "ready", 100, "Preparando instalación…")
        jobs.update_job(job["job_id"], "done", 100, "Actualización entregada al instalador.")
        with patch("updater.jobs.timezone.now", return_value=jobs.timezone.now() + jobs.timedelta(seconds=601)):
            jobs.cleanup_expired_jobs()
        self.assertIsNone(jobs.get_job(job["job_id"]))
