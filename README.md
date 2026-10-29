# NeuroflexW

Proyecto Capstone de Neuroflex: dashboard clínico y modelos de clasificación.

## Contenido

- `neuroflex-dashboard-master/`: aplicación web Django y sus recursos.
- `archivos_neuroflex/`: notebook y exportación ONNX del modelo de tres clases.
- Notebooks y scripts en la raíz: experimentos y preparación del modelo/dataset.

## Ejecutar el dashboard

Requiere Python 3.12. Desde `neuroflex-dashboard-master/`, instala dependencias con `pip install -r requirements.txt`, aplica migraciones con `python manage.py migrate` y arranca con `python manage.py runserver`. Consulta el README del dashboard para la configuración local.

Los registros de sesiones y los CSV con observaciones de participantes se mantienen fuera de este repositorio público. Los notebooks se guardaron sin resultados de ejecución para evitar incluir datos en sus salidas.
