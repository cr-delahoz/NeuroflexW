import tensorflow as tf
import pandas as pd
import numpy as np

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Input, Dropout, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

# =========================
# 1. Cargar dataset
# =========================

df = pd.read_csv("dataset_neuroflex.csv")

columnas_clasificadas = [
    'TiempoRespuestaPararse',
    'TiempoRespuestaPregunta1',
    'TiempoRespuestaPregunta2',
    'TiempoRespuestaPregunta3',
    'TiempoReaccionVisual',
    'TiempoCapturarNumero'
]

# =========================
# 2. Generar datos sintéticos
# =========================

np.random.seed(42)

filas_por_clase = 10000
filas_actuales_si = df[df['DeterioroCognitivo'] == 'Sí'].shape[0]
filas_actuales_no = df[df['DeterioroCognitivo'] == 'No'].shape[0]

nuevos_si = filas_por_clase - filas_actuales_si
nuevos_no = filas_por_clase - filas_actuales_no

estadisticas = {
    'TiempoRespuestaPararse':  {'mean': 2.4832, 'std': 0.7758, 'min': 1.0, 'max': 5.4322},
    'TiempoRespuestaPregunta1':{'mean': 2.9973, 'std': 0.9846, 'min': 1.0, 'max': 6.0},
    'TiempoRespuestaPregunta2':{'mean': 3.4917, 'std': 0.9910, 'min': 1.0, 'max': 6.5},
    'TiempoRespuestaPregunta3':{'mean': 4.0608, 'std': 1.2322, 'min': 1.0, 'max': 7.0},
    'TiempoReaccionVisual':    {'mean': 0.8095, 'std': 0.2422, 'min': 0.4, 'max': 1.5},
    'TiempoCapturarNumero':    {'mean': 2.4910, 'std': 0.6920, 'min': 1.0, 'max': 4.7718},
}

def generar_filas(n_filas, clase, factor_separacion=0.7):
    datos = {}

    for col, stats in estadisticas.items():
        if clase == 'Sí':
            media_ajustada = stats['mean'] + (stats['std'] * factor_separacion)
        else:
            media_ajustada = stats['mean'] - (stats['std'] * factor_separacion)

        valores = np.random.normal(media_ajustada, stats['std'], n_filas)
        valores = np.clip(valores, stats['min'], stats['max'])
        datos[col] = valores

    datos['DeterioroCognitivo'] = clase
    return pd.DataFrame(datos)

nuevos_datos_si = generar_filas(nuevos_si, 'Sí', factor_separacion=0.7)
nuevos_datos_no = generar_filas(nuevos_no, 'No', factor_separacion=0.7)

df_ampliado = pd.concat([df[columnas_clasificadas + ['DeterioroCognitivo']],
                         nuevos_datos_si,
                         nuevos_datos_no],
                        ignore_index=True)

print(df_ampliado['DeterioroCognitivo'].value_counts())

# =========================
# 3. Separar X e y
# =========================

X = df_ampliado[columnas_clasificadas].copy()
y = df_ampliado['DeterioroCognitivo'].map({'No': 0, 'Sí': 1})

# =========================
# 4. Train / Test estratificado
# =========================

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

# =========================
# 5. Regla clínica mejorada
# =========================

for col in columnas_clasificadas:
    X_train[col] = X_train[col].fillna(3.0)
    X_test[col] = X_test[col].fillna(3.0)

    # Nueva variable: indica si superó los 3 segundos
    X_train[col + "_sobre_3s"] = (X_train[col] > 3.0).astype(int)
    X_test[col + "_sobre_3s"] = (X_test[col] > 3.0).astype(int)

    # Aplicar tope clínico
    X_train[col] = X_train[col].clip(upper=3.0)
    X_test[col] = X_test[col].clip(upper=3.0)

# =========================
# 6. Escalamiento
# =========================

scaler = StandardScaler()

X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

X_train_tensor = tf.convert_to_tensor(X_train_scaled, dtype=tf.float32)
X_test_tensor = tf.convert_to_tensor(X_test_scaled, dtype=tf.float32)

y_train_tensor = tf.convert_to_tensor(y_train.values, dtype=tf.float32)
y_test_tensor = tf.convert_to_tensor(y_test.values, dtype=tf.float32)

# =========================
# 7. Modelo
# =========================

num_caracteristicas = X_train_tensor.shape[1]

modelo = Sequential([
    Input(shape=(num_caracteristicas,)),

    Dense(32, activation='relu'),
    BatchNormalization(),
    Dropout(0.15),

    Dense(16, activation='relu'),
    BatchNormalization(),
    Dropout(0.10),

    Dense(8, activation='relu'),

    Dense(1, activation='sigmoid')
])

modelo.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
    loss='binary_crossentropy',
    metrics=['accuracy']
)

modelo.summary()

# =========================
# 8. Callbacks
# =========================

early_stop = EarlyStopping(
    monitor='val_accuracy',
    patience=12,
    restore_best_weights=True,
    mode='max'
)

reduce_lr = ReduceLROnPlateau(
    monitor='val_loss',
    factor=0.5,
    patience=5,
    min_lr=0.00001
)

# =========================
# 9. Entrenamiento
# =========================

historial = modelo.fit(
    X_train_tensor,
    y_train_tensor,
    epochs=150,
    batch_size=64,
    validation_split=0.2,
    callbacks=[early_stop, reduce_lr],
    verbose=1
)

print(f"Entrenamiento detenido en epoch: {len(historial.history['loss'])}")

# =========================
# 10. Evaluación
# =========================

loss, acc = modelo.evaluate(X_test_tensor, y_test_tensor, verbose=0)

print(f"\nAccuracy en test: {acc:.4f}")

y_prob = modelo.predict(X_test_tensor)
y_pred = (y_prob >= 0.5).astype(int).ravel()

print("\nMatriz de confusión:")
print(confusion_matrix(y_test, y_pred))

print("\nReporte de clasificación:")
print(classification_report(y_test, y_pred, target_names=['No', 'Sí']))

# ============================================================
# FASE DE CONGELADO DEL MODELO
# ============================================================

import os
import json
import joblib
import hashlib
from datetime import datetime

# Carpeta donde se guardará el modelo congelado
CARPETA_MODELO = "modelo_neuroflex_congelado"
os.makedirs(CARPETA_MODELO, exist_ok=True)

# ------------------------------------------------------------
# 1. Guardar modelo entrenado en formato Keras
# ------------------------------------------------------------

ruta_modelo = os.path.join(CARPETA_MODELO, "modelo_neuroflex.keras")

modelo.save(ruta_modelo)

print(f"Modelo guardado en: {ruta_modelo}")


# ------------------------------------------------------------
# 2. Guardar scaler
# ------------------------------------------------------------

ruta_scaler = os.path.join(CARPETA_MODELO, "scaler_neuroflex.pkl")

joblib.dump(scaler, ruta_scaler)

print(f"Scaler guardado en: {ruta_scaler}")


# ------------------------------------------------------------
# 3. Guardar columnas usadas por el modelo
# ------------------------------------------------------------

columnas_modelo = list(X_train.columns)

ruta_columnas = os.path.join(CARPETA_MODELO, "columnas_modelo.json")

with open(ruta_columnas, "w", encoding="utf-8") as f:
    json.dump(columnas_modelo, f, ensure_ascii=False, indent=4)

print(f"Columnas guardadas en: {ruta_columnas}")


# ------------------------------------------------------------
# 4. Guardar metadata del modelo
# ------------------------------------------------------------

metadata = {
    "nombre_modelo": "NeuroFlex - Clasificador Deterioro Cognitivo",
    "version": "1.0.0",
    "fecha_congelado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "framework": "TensorFlow / Keras",
    "tipo_modelo": "Red neuronal binaria",
    "variable_objetivo": "DeterioroCognitivo",
    "clases": {
        "0": "No",
        "1": "Sí"
    },
    "umbral_clasificacion": 0.5,
    "columnas_entrada": columnas_modelo,
    "regla_clinica": "Los valores mayores a 3 segundos se topan en 3.0 y se agrega variable binaria *_sobre_3s",
    "accuracy_test": float(acc)
}

ruta_metadata = os.path.join(CARPETA_MODELO, "metadata_modelo.json")

with open(ruta_metadata, "w", encoding="utf-8") as f:
    json.dump(metadata, f, ensure_ascii=False, indent=4)

print(f"Metadata guardada en: {ruta_metadata}")


# ------------------------------------------------------------
# 5. Calcular hash MD5 del modelo congelado
# ------------------------------------------------------------

def calcular_md5(ruta_archivo):
    hash_md5 = hashlib.md5()

    with open(ruta_archivo, "rb") as f:
        for bloque in iter(lambda: f.read(4096), b""):
            hash_md5.update(bloque)

    return hash_md5.hexdigest()


md5_modelo = calcular_md5(ruta_modelo)

ruta_hash = os.path.join(CARPETA_MODELO, "hash_modelo.txt")

with open(ruta_hash, "w", encoding="utf-8") as f:
    f.write(f"Archivo: modelo_neuroflex.keras\n")
    f.write(f"MD5: {md5_modelo}\n")

print(f"MD5 del modelo: {md5_modelo}")
print(f"Hash guardado en: {ruta_hash}")


# ------------------------------------------------------------
# 6. Resumen final
# ------------------------------------------------------------

print("\nCongelado del modelo completado.")
print("Archivos generados:")

for archivo in os.listdir(CARPETA_MODELO):
    print("-", archivo)