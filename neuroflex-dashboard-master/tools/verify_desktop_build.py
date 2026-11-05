"""Check the actual PyInstaller archive, rather than the development imports.

Run with the build environment's Python after compiling neuroflex.spec.
No database records, credentials, or user reports are read or changed.
"""

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types

from PyInstaller.archive.readers import CArchiveReader


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


class BundledML(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, archive):
        self.archive = archive

    def find_spec(self, fullname, path=None, target=None):
        if (fullname == "ml" or fullname.startswith("ml.")) and fullname in self.archive.toc:
            return importlib.util.spec_from_loader(
                fullname, self, is_package=self.archive.toc[fullname][0] == 1
            )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = f"<neuroflex.exe:{module.__name__}>"
        exec(self.archive.extract(module.__name__), module.__dict__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=BASE_DIR / "dist/neuroflex")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    bundle = args.dist.resolve()
    reader = CArchiveReader(str(bundle / "neuroflex.exe"))
    archive = reader.open_embedded_archive("PYZ.pyz")
    # Force every ML import, including the joblib estimator class, to come
    # from the compiled executable under test.
    sys.meta_path.insert(0, BundledML(archive))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.test import override_settings
    from django.utils import timezone
    from ml.services import predict_cognitive_result
    from ml.services import performance_feature_builder
    from reports.models import ReportRequest

    assert not hasattr(performance_feature_builder, "HAND_CODES"), "Stale hand parsing in the executable"
    metrics = json.loads((BASE_DIR.parent / "postman/metricas_ejemplo.json").read_text())
    features = performance_feature_builder.build_performance_features(metrics)
    assert math.isnan(features["dominant_hand"])
    model_name = "dropout_objects_model.joblib"
    source_model = BASE_DIR / "ml/model_artifacts" / model_name
    bundled_model = bundle / "_internal/ml/model_artifacts" / model_name
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(source_model) == digest(bundled_model), "Bundled model does not match the frozen model"
    for item in bundle.rglob("*"):
        if item.is_file():
            relative = item.relative_to(bundle).as_posix()
            assert item.name not in {".env", "db.sqlite3", "security-audit.jsonl"}, relative
            assert item.suffix.lower() not in {".sqlite3", ".db"}, relative
            assert not relative.startswith(("_internal/media/", "_internal/private_reports/", "_internal/clinical_sessions/data/local_sessions/")), relative

    with override_settings(COGNITIVE_MODEL_DIR=bundled_model.parent):
        result = predict_cognitive_result(metrics)
        assert result["available"], result
        assert result["predicted_class"] == "alto", result
        for hand in (1, 2, 3, "invalid"):
            repeated = predict_cognitive_result(
                dict(metrics, ManoPredominante=hand), {"dominant_hand": hand}
            )
            assert repeated["probabilities"] == result["probabilities"]

        # Exercise the PDF functions compiled into this executable as well.
        report_module = types.ModuleType("reports._verify_desktop")
        report_module.__package__ = "reports"
        exec(archive.extract("reports.services"), report_module.__dict__)
        now = timezone.now()
        report = ReportRequest(
            pk=0, session_id="SYNTHETIC-BUILD-CHECK",
            requested_by=get_user_model()(username="build-check"),
            requested_at=now, generated_at=now,
        )
        normalized = report_module.normalize_snapshot_for_report({
            "session_id": report.session_id, "created_at": now.isoformat(), "metrics": metrics,
        })
        pdf_bytes = report_module.build_pdf_bytes(report, normalized)
        assert b"Resultado del modelo congelado" not in pdf_bytes
        assert b"Puntuacion tecnica" not in pdf_bytes
        assert b"estimado: alto" in pdf_bytes
        for label in (b"bajo", b"medio", b"alto"):
            assert b"Probabilidad " + label not in pdf_bytes
        assert b"Mano predominante" not in pdf_bytes
        assert b"Mano dominante" not in pdf_bytes
        assert b"Resultado no disponible" not in pdf_bytes
        for removed in (b"Observaciones del especialista", b"Trazabilidad", b"Advertencias", b"INFORMACION IMPORTANTE"):
            assert removed not in pdf_bytes
        assert b"/Count 3" in pdf_bytes
        assert b"Pagina 3 de 3" in pdf_bytes
        incomplete = dict(metrics)
        del incomplete["TiempoCapturarNumero"]
        normalized = report_module.normalize_snapshot_for_report({"metrics": incomplete})
        unavailable_pdf = report_module.build_pdf_bytes(report, normalized)
        assert b"(0.000)" not in unavailable_pdf
        assert b"Puntuacion tecnica" not in unavailable_pdf
        assert b"Resultado del modelo congelado" not in unavailable_pdf

    summary = {
        "executable": str(bundle / "neuroflex.exe"),
        "compiled_modules_verified": True,
        "hand_input_ignored": True,
        "model_sha256": digest(bundled_model),
        "private_data_excluded": True,
        "pdf_result_verified": True,
        "pdf_technical_score_and_section_4_1_removed": True,
        "pdf_sections_5_6_7_removed": True,
        "pdf_pages": 3,
        "unavailable_result_does_not_become_zero": True,
        "synthetic_result": {"class": result["predicted_class"], "probabilities": result["probabilities"]},
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
