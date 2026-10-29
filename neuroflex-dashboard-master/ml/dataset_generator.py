import os
import json
import pandas as pd


# ============================================================
# CONFIGURACIÓN
# ============================================================

CARPETA_DATOS = "data"
ARCHIVO_SALIDA = "dataset_neuroflex_generado.csv"

# Columnas que usa tu modelo
COLUMNAS_MODELO = [
    "TiempoRespuestaPararse",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoReaccionVisual",
    "TiempoCapturarNumero",
    "DeterioroCognitivo"
]


# ============================================================
# FUNCIÓN PARA LEER UN JSON NEUROFLEX
# ============================================================

def leer_archivo_json(ruta_archivo):
    """
    Lee un archivo JSON de NeuroFlex y devuelve una fila compatible
    con el formato del CSV usado para entrenar el modelo.
    """

    with open(ruta_archivo, "r", encoding="utf-8") as archivo:
        contenido = json.load(archivo)

    datos = contenido.get("data", {})
    paciente = contenido.get("patient_info", {})

    fila = {
        "TiempoRespuestaPararse": datos.get("TiempoRespuestaPararse"),
        "TiempoRespuestaPregunta1": datos.get("TiempoRespuestaPregunta1"),
        "TiempoRespuestaPregunta2": datos.get("TiempoRespuestaPregunta2"),
        "TiempoRespuestaPregunta3": datos.get("TiempoRespuestaPregunta3"),
        "TiempoReaccionVisual": datos.get("TiempoReaccionVisual"),
        "TiempoCapturarNumero": datos.get("TiempoCapturarNumero"),

        # Como el JSON no trae esta etiqueta, queda vacía.
        # Puedes completarla después manualmente o con una regla.
        "DeterioroCognitivo": None
    }

    # Datos extra opcionales, útiles para auditoría
    fila["_archivo_origen"] = os.path.basename(ruta_archivo)
    fila["_carpeta_origen"] = os.path.basename(os.path.dirname(ruta_archivo))
    fila["_timestamp"] = contenido.get("timestamp")
    fila["_session_id"] = contenido.get("session_id")
    fila["_nombre_paciente"] = paciente.get("name")
    fila["_edad"] = paciente.get("age")
    fila["_rut"] = paciente.get("rut")
    fila["_mano_dominante"] = paciente.get("dominant_hand")

    return fila


# ============================================================
# RECORRER TODAS LAS CARPETAS Y ARCHIVOS JSON
# ============================================================

filas = []

for carpeta_actual, subcarpetas, archivos in os.walk(CARPETA_DATOS):
    for nombre_archivo in archivos:
        if nombre_archivo.lower().endswith(".json"):
            ruta_archivo = os.path.join(carpeta_actual, nombre_archivo)

            try:
                fila = leer_archivo_json(ruta_archivo)
                filas.append(fila)

                print(f"Leído correctamente: {ruta_archivo}")

            except Exception as error:
                print(f"Error leyendo {ruta_archivo}: {error}")


# ============================================================
# CREAR DATAFRAME
# ============================================================

df = pd.DataFrame(filas)

print("\nTotal de archivos JSON leídos:", len(df))

if len(df) == 0:
    print("No se encontraron archivos JSON.")
    exit()


# ============================================================
# LIMPIEZA BÁSICA
# ============================================================

# Convertir columnas numéricas
columnas_numericas = [
    "TiempoRespuestaPararse",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoReaccionVisual",
    "TiempoCapturarNumero",
    "_edad"
]

for col in columnas_numericas:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")


# ============================================================
# GUARDAR CSV COMPLETO CON DATOS DE AUDITORÍA
# ============================================================

df.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print(f"\nCSV completo generado: {ARCHIVO_SALIDA}")


# ============================================================
# GUARDAR CSV SOLO CON FORMATO DEL MODELO
# ============================================================

ARCHIVO_MODELO = "dataset_neuroflex_formato_modelo.csv"

df_modelo = df[COLUMNAS_MODELO].copy()

df_modelo.to_csv(ARCHIVO_MODELO, index=False, encoding="utf-8-sig")

print(f"CSV para modelo generado: {ARCHIVO_MODELO}")


# ============================================================
# RESUMEN
# ============================================================

print("\nVista previa del dataset para modelo:")
print(df_modelo.head())

print("\nValores nulos por columna:")
print(df_modelo.isna().sum())