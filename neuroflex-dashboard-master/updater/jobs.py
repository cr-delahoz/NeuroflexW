import threading
import uuid
from copy import copy
from datetime import timedelta

from django.utils import timezone

TERMINAL_RETENTION_SECONDS = 600
TERMINAL_STATUSES = {"done", "error"}
ACTIVE_STATUSES = {"pending", "downloading", "ready"}
VALID_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
ALLOWED_TRANSITIONS = {
    "pending": {"downloading", "error"},
    "downloading": {"downloading", "ready", "error"},
    "ready": {"done", "error"},
    "done": set(),
    "error": set(),
}
_jobs = {}
_jobs_lock = threading.RLock()
_update_slot = threading.Lock()


def _copy(job):
    return copy(job)


def cleanup_expired_jobs():
    cutoff = timezone.now() - timedelta(seconds=TERMINAL_RETENTION_SECONDS)
    with _jobs_lock:
        for job_id, job in list(_jobs.items()):
            if job["status"] in TERMINAL_STATUSES and job["updated_at"] < cutoff:
                del _jobs[job_id]


def create_job():
    with _jobs_lock:
        cleanup_expired_jobs()
        for job in _jobs.values():
            if job["status"] in ACTIVE_STATUSES:
                return _copy(job), True
        if not _update_slot.acquire(blocking=False):
            for job in _jobs.values():
                if job["status"] in ACTIVE_STATUSES:
                    return _copy(job), True
            raise RuntimeError("El actualizador está ocupado sin un trabajo visible.")
        now = timezone.now()
        job = {"job_id": uuid.uuid4().hex, "status": "pending", "percentage": None,
               "message": "Preparando actualización…", "created_at": now, "updated_at": now}
        _jobs[job["job_id"]] = job
        return _copy(job), False


def get_job(job_id):
    cleanup_expired_jobs()
    with _jobs_lock:
        job = _jobs.get(job_id)
        return _copy(job) if job else None


def update_job(job_id, status, percentage, message):
    if status not in VALID_STATUSES:
        raise ValueError("Estado de actualización no válido.")
    if percentage is not None and not isinstance(percentage, int):
        raise ValueError("El progreso debe ser entero o nulo.")
    if percentage is not None and not (0 <= percentage <= 100):
        raise ValueError("El progreso debe estar entre 0 y 100.")
    with _jobs_lock:
        job = _jobs[job_id]
        current_status = job["status"]
        if status not in ALLOWED_TRANSITIONS.get(current_status, set()):
            raise ValueError(f"Transición de estado no válida: {current_status!r} → {status!r}.")
        job.update(status=status, percentage=percentage, message=message, updated_at=timezone.now())
        return _copy(job)


def is_update_running():
    return _update_slot.locked()


def cleanup_job(job_id):
    with _jobs_lock:
        if job_id not in _jobs:
            return
        if _update_slot.locked():
            _update_slot.release()


def reset_jobs_for_tests():
    with _jobs_lock:
        _jobs.clear()
        if _update_slot.locked():
            _update_slot.release()
