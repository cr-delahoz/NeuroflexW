#!/usr/bin/env python3
"""Create row-wise synthetic Neuroflex sessions from the real dataset.

Synthetic rows are derived from one real session at a time so that the
relationships between its columns are retained. ``source_session_id`` records
the originating session for both real and synthetic rows, allowing downstream
notebooks to prevent train/test leakage. Direct patient identifiers are omitted.
"""
import csv
import os
import random
import uuid
from datetime import datetime, timedelta

INPUT = 'neuroflex_dataset.csv'
OUTPUT = 'neuroflex_dataset_augmented.csv'
TARGET_ROWS = 6000
SEED = 42
NOISY_TIME_COLUMNS = {
    'TiempoRespuestaPararse',
    'TiempoActivoTarea',
    'TiempoRespuestaPregunta1',
    'TiempoRespuestaPregunta2',
    'TiempoRespuestaPregunta3',
    'TiempoCapturarNumero',
    'TiempoTutorial',
}

random.seed(SEED)

if not os.path.exists(INPUT):
    raise SystemExit(f'ERROR: no se encuentra {INPUT} en el directorio actual')

with open(INPUT, 'r', encoding='utf-8-sig', newline='') as source:
    reader = csv.DictReader(source)
    columns = list(reader.fieldnames or [])
    real_rows = list(reader)

if not real_rows:
    raise SystemExit('ERROR: el dataset original no contiene filas')
if 'session_id' not in columns:
    raise SystemExit('ERROR: falta la columna session_id para rastrear el origen')

columns = [column for column in columns if column not in {'name', 'rut'}]
real_rows = [
    {column: row.get(column, '') for column in columns}
    for row in real_rows
]
output_columns = columns + (['source_session_id'] if 'source_session_id' not in columns else [])
rows = []
for row in real_rows:
    clean = {column: row.get(column, '') for column in columns}
    clean['source_session_id'] = row.get('session_id', '')
    rows.append(clean)

synthetic_count = max(0, TARGET_ROWS - len(real_rows))
for index in range(synthetic_count):
    source_row = random.choice(real_rows)
    synthetic = dict(source_row)
    source_id = source_row['session_id']

    synthetic['session_id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, f'neuroflex:{SEED}:{index}'))
    synthetic['source_session_id'] = source_id

    # Keep the session's observed category and outcome counts intact. Perturb
    # only continuous response times, together, within that source session.
    for column in NOISY_TIME_COLUMNS:
        raw = source_row.get(column, '')
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        sigma = max(1e-6, abs(value) * 0.02)
        synthetic[column] = f'{max(0.0, random.gauss(value, sigma)):.6f}'

    raw_timestamp = source_row.get('timestamp', '')
    try:
        base_timestamp = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
        synthetic_timestamp = base_timestamp + timedelta(seconds=random.randint(1, 86400))
        synthetic['timestamp'] = synthetic_timestamp.isoformat()
        if 'date' in output_columns:
            synthetic['date'] = synthetic_timestamp.date().isoformat()
    except (TypeError, ValueError):
        pass

    if 'patient_updated_at' in output_columns and synthetic.get('timestamp'):
        synthetic['patient_updated_at'] = synthetic['timestamp']

    rows.append(synthetic)

with open(OUTPUT, 'w', encoding='utf-8', newline='') as destination:
    writer = csv.DictWriter(destination, fieldnames=output_columns)
    writer.writeheader()
    writer.writerows(rows)

print(f'Filas reales: {len(real_rows)}')
print(f'Filas sintéticas generadas: {synthetic_count}')
print(f'Total: {len(rows)}')
print(f'Archivo guardado en {OUTPUT}')
