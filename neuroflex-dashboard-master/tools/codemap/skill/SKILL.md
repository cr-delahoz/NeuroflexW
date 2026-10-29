---
name: codemap-annotate
description: You MUST use this before telling the user that a task is finished whenever you created, modified, moved or deleted files in a git repository (directly or through subagents). Registra en Codemap un resumen en lenguaje natural de cada cambio para que el usuario lo revise sin leer el diff. Úsala también cuando el usuario pida "anota los cambios", "codemap", "qué cambiaste", "resume los cambios", "revisemos lo que hiciste" o cuando un mensaje "[Codemap]" lo indique.
---

# Anotar los cambios en Codemap

Codemap detecta por su cuenta, a partir del `git diff`, cada cambio del repositorio (funciones, clases,
archivos). Tu trabajo es **explicar cada uno en lenguaje natural**. El usuario va a contrastar lo que dices
con el código, y los cambios que no anotes aparecerán como **"no declarados por la IA"**.

Comando de Codemap (ejecútalo desde la raíz del repositorio en el que trabajaste):

```bash
python "{{CODEMAP}}" <comando> --repo .
```

## Pasos

1. **Lista los cambios detectados:**
   ```bash
   python "{{CODEMAP}}" scan --repo . --json - --compact
   ```
   Cada elemento de `cambios` tiene un `id` (`archivo::símbolo`, o `archivo::*` para el archivo completo), el
   resumen automático (`resumen`), `etiquetas` de riesgo y `evidencia` (líneas). Usa los `id` **exactamente**
   como aparecen.

2. **Registra las anotaciones con un único comando** (sin archivos temporales): `--tarea` una vez, `--autor` con
   el nombre de tu herramienta (`claude-code`, `opencode`, `cursor`…) y un `--cambio ID 'RESUMEN'` por cada id:
   ```bash
   python "{{CODEMAP}}" annotate --repo . --autor claude-code \
     --tarea 'El usuario pidió X. Se hizo Y y Z.' \
     --cambio reports/views.py::approve_request 'Al aprobar una solicitud ahora también se avisa por correo al especialista.' \
     --cambio 'templates/reports/list.html::*' 'La tabla de solicitudes muestra una columna nueva con la fecha de aprobación.'
   ```
   Escribe cada texto entre **comillas simples** (funciona igual en bash y PowerShell) y no uses comillas simples
   dentro del texto. Pon también entre comillas simples los ids que terminan en `::*`. En PowerShell, cambia `\`
   por un acento grave (`` ` ``) al partir líneas, o escribe todo en una sola línea.
   Si hay muchos cambios, también puedes pasar un JSON `{"tarea", "autor", "cambios": {id: resumen}}` por la
   entrada estándar con `annotate --repo . -`.

3. **Lee el informe de `annotate`.** Si termina con código 1:
   - **Cambios sin anotar:** vuelve a ejecutar `annotate` solo con los `--cambio` que faltan (las anotaciones se fusionan).
   - **Ids que no corresponden a ningún cambio:** corrige el id o elimina esa anotación; no describas cambios que no existen.
   - **Anotaciones desactualizadas:** el código cambió después de anotarlo; vuelve a escribir esos resúmenes.
   - **Falta 'tarea':** repite el comando con `--tarea`.

4. **Avísale al usuario** en tu respuesta final que los cambios están anotados y que puede revisarlos con
   `python "{{CODEMAP}}" serve --repo . --open`.

## Cómo escribir cada resumen

- **Una o dos frases, en el idioma del usuario y en lenguaje de negocio.** Di qué hace ahora el programa y para qué, no qué líneas cambiaron. Puedes nombrar la función entre comillas invertidas si ayuda.
  - Mal: "Se añadió un `if` en la línea 40 y se cambió el return."
  - Bien: "Las solicitudes rechazadas ya no se pueden volver a aprobar; antes se podía por error."
- **Describe solo lo que está en ese cambio.** Si no estás seguro de lo que hace, revisa sus líneas (`evidencia`) antes de escribir.
- **No suavices los riesgos.** Si el cambio borra datos, quita un control de acceso, maneja contraseñas o claves, ejecuta procesos o hace llamadas de red, dilo explícitamente. Las etiquetas de Codemap se muestran de todos modos.
- **Si encuentras un cambio que no hiciste a propósito** (un archivo generado, un efecto secundario, algo de otra tarea), no inventes una justificación: anótalo como tal ("Cambio no intencional: …" o "No lo hice yo: …") y menciónalo al usuario.
- `tarea`: una o dos frases con lo que se pidió y lo que se hizo, incluido lo que quedó pendiente.

## Qué no hacer

- No edites a mano los archivos de `tools/codemap/out/`; usa siempre `annotate`.
- No crees archivos para anotar (ni dentro ni fuera del repo): todo cabe en el comando `annotate`.
- No ejecutes `annotate --clear` salvo que el usuario lo pida: borra lo anotado.
- No anotes cambios en bloque con un texto genérico ("refactor general") para que desaparezca la alerta.
