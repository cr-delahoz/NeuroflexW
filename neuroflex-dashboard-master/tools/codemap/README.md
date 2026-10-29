# Codemap

Revisar lo que cambió en un repositorio (por ejemplo, lo que hizo una IA) **sin leer el diff línea por línea**:
un feed agrupado por sección, con un resumen de una línea por cambio, etiquetas de riesgo y el código como
evidencia a un clic.

Iteración actual: **fases 1 y 2** (CLI + página local). Solo usa la biblioteca estándar de Python (3.10+) y git.
No hay LLM todavía: los resúmenes salen de plantillas deterministas.

## Uso

Desde la raíz del repositorio a revisar:

```bash
python tools/codemap/codemap.py scan
```

```bash
python tools/codemap/codemap.py serve --open
```

| Comando | Qué hace |
|---|---|
| `scan` | Muestra el feed en la terminal. `--json RUTA` guarda el resultado (`--json -` lo imprime). |
| `report [--open]` | Genera `tools/codemap/out/report.html`, una página que funciona sin conexión. |
| `serve [--port 8765] [--open]` | Sirve la página en `http://127.0.0.1:8765/`; cada recarga vuelve a analizar el repositorio. `/api/cambios` devuelve el JSON. |
| `annotate --tarea T --cambio ID RESUMEN …` | Registra lo que la IA dice que hizo en cada cambio (ver [Anotaciones de la IA](#anotaciones-de-la-ia)). También acepta un JSON (`annotate ARCHIVO` o `-`). `--clear` borra las anotaciones. |
| `install-skill [--dest RUTA] [--force]` | Copia la skill `codemap-annotate` a `~/.claude/skills/`. |
| `install-opencode-plugin [--dest RUTA] [--force]` | Copia el plugin que exige anotar al terminar a `~/.config/opencode/plugins/`. |

Opciones comunes:

- `--base REF`: compara contra un commit o una rama (por defecto, `HEAD`). Por ejemplo, `--base HEAD~3` muestra todo lo que cambió en los últimos tres commits más lo que todavía no se commiteó.
- `--staged`: analiza solo lo que está en el índice (`git add`).
- `--repo RUTA`: analiza otro repositorio.
- `--config RUTA`: usa otras reglas de secciones.

Por defecto se comparan el árbol de trabajo y los archivos sin seguimiento contra la base. La carpeta
`tools/codemap/` se excluye para que la herramienta no se reporte a sí misma.

## Qué muestra

Cada cambio tiene este formato (ver `codemap_core/model.py`):

```json
{
  "id": "app/views.py::calcular",
  "seccion": "Backend / Vistas",
  "archivo": "app/views.py",
  "simbolo": "calcular",
  "tipo_simbolo": "función",
  "tipo_cambio": "modificado",
  "resumen": "Se modificó la función `calcular()` (+2 / −1 líneas): cambian sus parámetros; ahora también hace llamadas de red.",
  "resumen_tecnico": "[MODIFICADO] función calcular · app/views.py:9-12 · +2/−1 · firma: `def calcular(a, b)` → `def calcular(a, b, c=0)` · etiquetas: red",
  "resumen_origen": "regla",
  "etiquetas": ["red"],
  "riesgo": 2,
  "lineas": {"añadidas": 2, "eliminadas": 1},
  "evidencia": [{"archivo": "app/views.py", "linea_inicio": 10, "linea_fin": 11, "lado": "nuevo"}]
}
```

- **Unidad de revisión.** En Python y JavaScript, cada cambio corresponde a una función, un método o una clase. En plantillas HTML y Markdown hay un cambio por archivo, con la lista de bloques o apartados afectados. En el resto de los archivos, un cambio por archivo.
- **Tipos de cambio:** nuevo, modificado, eliminado y movido. Detecta funciones renombradas (cuerpo parecido con otro nombre) y archivos movidos, incluso a carpetas que todavía no están en git.
- **Etiquetas** (`codemap_core/tags.py`): red, escribe en disco, borrado, base de datos, ejecuta procesos, secretos, permisos, **quita permisos** (también se buscan en las líneas eliminadas), desactiva CSRF, dependencias y error de sintaxis. El código que solo se movió o se reindentó no genera etiquetas.
- **Riesgo:** 3 = alto (borrado, secretos, quitar controles de acceso), 2 = medio y 1 = bajo. Dentro de cada sección, los cambios se ordenan de mayor a menor riesgo.

## Anotaciones de la IA

El agente que hizo los cambios es quien mejor sabe *por qué* los hizo. La skill [`skill/SKILL.md`](skill/SKILL.md)
le indica que, al terminar cada tarea, escriba un resumen en lenguaje natural de cada cambio que detectó Codemap:

```bash
python tools/codemap/codemap.py install-skill
```

La copia queda en `~/.claude/skills/codemap-annotate/`, con la ruta absoluta de este `codemap.py`. Si mueves el
repositorio, vuelve a ejecutarla con `--force`.

Qué hace el agente:

1. Ejecuta `scan --json - --compact`, que lista los cambios con su `id` (`archivo::símbolo`).
2. Ejecuta un único comando: `annotate --autor opencode --tarea '…' --cambio <id> '<resumen>' …`. No crea archivos temporales, así que en el agente basta con autorizar una vez `python ".../codemap.py" *`.
3. Si `annotate` devuelve 1, el informe explica qué falta (cambios sin anotar, ids inventados o la tarea) y el agente lo completa.

**El diff sigue siendo la fuente de verdad.** La anotación es lo que la IA *dice* que hizo, y Codemap la contrasta:

| Estado | Significado |
|---|---|
| anotado | La IA describió el cambio y el código no cambió desde entonces. |
| **no declarado** | El cambio está en el código pero la IA no lo mencionó. Aparece primero en la página. |
| desactualizado | El código cambió después de anotarlo (la huella `huella` ya no coincide). |
| declaración sin respaldo | La IA anotó un `id` que no corresponde a ningún cambio. |

En la página, el texto de la IA lleva la marca «según la IA», y debajo queda siempre el resumen que Codemap calcula
del diff. Las etiquetas de riesgo son deterministas: la IA no puede quitarlas.

Las anotaciones se guardan en `out/anotaciones/<commit base>.json` (fuera de git) y se fusionan entre llamadas.
Como cada archivo corresponde a un commit base, después de commitear se pueden seguir viendo con `--base <ese commit>`.

Para otros agentes (opencode, Cursor) sirven las mismas instrucciones de `SKILL.md`: solo hacen falta los comandos `scan` y `annotate`.

### opencode: activación automática

opencode encuentra la skill en `~/.claude/skills/` sin hacer nada más. Por sí sola, la skill depende de que el
modelo se acuerde de usarla al terminar. El plugin [`opencode/codemap.js`](opencode/codemap.js) lo exige:

```bash
python tools/codemap/codemap.py install-opencode-plugin
```

El plugin queda en `~/.config/opencode/plugins/codemap.js`, con rutas absolutas a este Python y a este `codemap.py`.
Hay que reiniciar opencode para que lo cargue. Funciona así:

1. Con el primer mensaje de una sesión guarda una foto de los cambios que ya existían. No reclama nada de lo que estaba antes.
2. Cada vez que la sesión principal termina de responder (`session.idle`), ejecuta `scan`. Si la sesión dejó cambios sin anotar o con la anotación desactualizada, le envía al agente un mensaje `[Codemap]` con la lista y le pide usar `codemap-annotate`. Esto incluye los cambios hechos con `bash` o por subagentes.
3. Los subagentes no reciben avisos. Hay como máximo 2 avisos por sesión y nunca dos por el mismo conjunto de cambios, para evitar bucles.

`CODEMAP_OPENCODE_DISABLE=1` lo desactiva. `CODEMAP_OPENCODE_LOG=<ruta>` registra en un archivo lo que hace
(útil para diagnosticar), y `CODEMAP_STORE` cambia la carpeta de anotaciones (lo usan los tests).

Notas de la prueba real con opencode 1.18:

- La primera vez, opencode pide permiso para ejecutar `python ".../codemap.py" ...`. Elige **"always"** para no tener que confirmar cada anotación. Si tu agente restringe `bash` (como `orchestrator`), añade la regla `"python *codemap.py*": allow`.
- `opencode run` (modo no interactivo) termina antes de que el plugin reciba `session.idle`, así que el aviso solo funciona en la TUI o con `opencode serve`.

## Secciones

Se definen en `codemap.config.json`. Para cada archivo se aplica la primera regla que coincide; los archivos que
no coinciden con ninguna quedan en "Sin clasificar". Cada regla admite:

- `rutas`: globs; `**/` equivale a cualquier número de carpetas.
- `contenido`: expresiones regulares que se buscan en el contenido del archivo.

Para otro proyecto basta con cambiar este JSON.

## Decisiones de diseño

1. **El parser da la verdad; el texto se deriva de él.** Cada resumen se construye solo con campos del modelo (símbolo, conteos, firma, decoradores, etiquetas). Ningún resumen menciona algo que no esté en el diff. Cuando llegue el LLM, solo reformulará esos datos (`resumen_origen` dirá `"llm"`).
2. **Siempre se puede ver el código.** Un resumen convincente pero falso es peor que no tener resumen, así que cada cambio enlaza a sus líneas.
3. **Se detectan los controles de acceso eliminados.** Quitar un `@login_required` es tan importante como añadir una llamada de red.
4. **Los identificadores son estables** (`archivo::símbolo`). Así, en la fase 6 se podrá comparar lo que la IA dice que hizo con lo que realmente cambió.
5. **Sin dependencias.** `ast` cubre Python con exactitud; HTML, JS y Markdown usan heurísticas. Para más lenguajes, tree-sitter se puede añadir en `symbols.py` sin tocar el resto.

## Estructura

```
codemap.py                # punto de entrada
codemap.config.json       # secciones y exclusiones
codemap_core/
  gitsource.py            # llamadas a git (diff, archivos sin seguimiento, git show)
  diffparse.py            # parser de unified diff
  symbols.py              # funciones/clases (ast), bloques Django, funciones JS, apartados Markdown
  sections.py             # reglas de secciones
  tags.py                 # etiquetas de efectos secundarios
  moves.py                # archivos movidos (borrado + nuevo parecidos)
  analyze.py              # orquestador -> ChangeSet
  summarize.py            # plantillas de resumen simple / técnico
  model.py                # contrato de datos
  annotations.py          # anotaciones de la IA: guardar, fusionar, contrastar con el diff
  render.py, server.py, templates/report.html   # página local
skill/SKILL.md            # skill codemap-annotate (fuente; se instala con install-skill)
opencode/codemap.js       # plugin de opencode (fuente; se instala con install-opencode-plugin)
tests/                    # unittest con repositorios git temporales
```

## Tests

```bash
python -m unittest discover -s tools/codemap/tests
```

Se usa `unittest` y no `pytest` para no activar el `pytest.ini` del proyecto Django.

## Hoja de ruta

| Fase | Qué falta | Dónde se integra |
|---|---|---|
| 3. Contexto + LLM | **En parte resuelta con las anotaciones de la IA.** Falta `context.md` (glosario, nivel del lector) para que la skill escriba con los términos del negocio, y un LLM externo para los cambios que no hizo un agente. | `SKILL.md` puede leer `context.md`; un LLM externo usaría el mismo `annotate`. |
| 4. Watcher + línea base | Guardar un commit o snapshot como "último revisado" y un botón **Marcar como revisado** que lo mueva. | `--base` ya acepta cualquier referencia; falta el almacenamiento (en `tools/codemap/out/`) y un `POST` en `server.py`. |
| 5. Enganches | opencode, Cursor y nvim: abrir o actualizar la página cuando el agente termina. | Llamar a `serve` o a `/api/cambios`. |
| 6. Cambios no declarados | **Hecha con `annotate` + skill, y exigida en opencode con el plugin.** Falta el equivalente en Claude Code (hook `Stop`) y en Cursor. | Reutilizan `scan --compact` y `annotate`. |
| 7. Setup interactivo | Generar `context.md` y las secciones automáticamente. | Escribir `codemap.config.json` y `context.md`. |

Antes de pasar a la fase 3, conviene medir el tiempo que lleva revisar un cambio real con `git diff` y con Codemap.

## Limitaciones conocidas

- En HTML, JS y Markdown los símbolos se detectan con heurísticas; un archivo que no se puede analizar se trata a nivel de archivo.
- Las etiquetas son patrones de texto: pueden dar falsos positivos (`.save(` de una imagen se marca como "base de datos") o pasar por alto llamadas indirectas.
- Si una función se mueve a otro archivo, aparece como eliminada en uno y nueva en el otro.
