import csv
import glob
import json
import os

root = os.path.join("/Users/cristobal/Desktop/Capstone", "Neuroflex-data")
out_file = os.path.join("/Users/cristobal/Desktop/Capstone", "neuroflex_dataset.csv")

fieldnames = [
    "timestamp",
    "session_id",
    "date",
    "age",
    "dominant_hand",
    "patient_updated_at",
    "TiempoRespuestaPararse",
    "Precision",
    "TiempoActivoTarea",
    "CantAciertasTotales",
    "ObjetosInteractuadosCorrectamente",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoCapturarNumero",
    "TiempoTutorial",
    "TipoEscena",
]

rows = []
for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        continue

    data = obj.get("data") or {}
    patient = obj.get("patient_info") or {}

    row = {
        "timestamp": obj.get("timestamp", ""),
        "session_id": obj.get("session_id", ""),
        "date": obj.get("timestamp", "")[:10] if obj.get("timestamp") else "",
        "age": patient.get("age", ""),
        "dominant_hand": patient.get("dominant_hand", ""),
        "patient_updated_at": patient.get("updated_at", ""),
    }

    for key in [
        "TiempoRespuestaPararse",
        "Precision",
        "TiempoActivoTarea",
        "CantAciertasTotales",
        "ObjetosInteractuadosCorrectamente",
        "TiempoRespuestaPregunta1",
        "TiempoRespuestaPregunta2",
        "TiempoRespuestaPregunta3",
        "TiempoCapturarNumero",
        "TiempoTutorial",
        "TipoEscena",
    ]:
        row[key] = data.get(key, "")

    rows.append(row)

rows = sorted(rows, key=lambda r: r.get("timestamp", ""))

with open(out_file, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Dataset creado en: {out_file}")
print(f"Total de registros: {len(rows)}")
print("Vista previa:")
with open(out_file, "r", encoding="utf-8") as csvfile:
    for i, line in enumerate(csvfile):
        print(line.rstrip())
        if i >= 2:
            break
