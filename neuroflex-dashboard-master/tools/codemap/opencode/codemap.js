/**
 * Plugin de Codemap para opencode.
 *
 * Al empezar una sesión guarda una foto de los cambios que ya existían en el repo.
 * Cada vez que la sesión principal termina de responder (`session.idle`), vuelve a
 * analizar el repo con Codemap: si la sesión dejó cambios sin anotar (o con una
 * anotación desactualizada), le pide al agente que use la skill `codemap-annotate`.
 *
 * - Solo actúa en la sesión principal: los subagentes (sesiones con parentID) no se
 *   interrumpen, pero sus cambios se reclaman al terminar la sesión principal.
 * - Como mucho MAX_NUDGES avisos por sesión y nunca dos veces por el mismo conjunto
 *   de cambios: evita bucles si el modelo no anota.
 * - CODEMAP_OPENCODE_DISABLE=1 lo desactiva.
 *
 * Fuente: tools/codemap/opencode/codemap.js. Se instala con
 * `python tools/codemap/codemap.py install-opencode-plugin`, que rellena las rutas.
 */

import { appendFileSync } from "node:fs";

const PYTHON = "{{PYTHON}}";
const CODEMAP = "{{CODEMAP}}";
const MAX_NUDGES = 2;
const MAX_LISTED = 10;

// CODEMAP_OPENCODE_LOG=<ruta> deja un registro de lo que hace el plugin (diagnóstico).
function log(...parts) {
  const target = process.env.CODEMAP_OPENCODE_LOG;
  if (!target) return;
  const text = parts.map((p) => (typeof p === "string" ? p : JSON.stringify(p))).join(" ");
  try {
    appendFileSync(target, `${new Date().toISOString()} ${text}\n`);
  } catch {
    // el registro nunca debe romper la sesión
  }
}

export const CodemapPlugin = async ({ client, $, directory }) => {
  if (process.env.CODEMAP_OPENCODE_DISABLE) return {};
  log("cargado", directory);

  const parents = new Map();   // sessionID -> parentID | null
  const baselines = new Map(); // sesión principal -> Set("id@huella") previos, o null si no aplica
  const nudges = new Map();    // sesión principal -> { count, key }

  async function isSubagent(sessionID) {
    if (!parents.has(sessionID)) {
      try {
        const res = await client.session.get({ path: { id: sessionID } });
        parents.set(sessionID, res?.data?.parentID ?? null);
      } catch {
        parents.set(sessionID, null);
      }
    }
    return Boolean(parents.get(sessionID));
  }

  async function scan() {
    try {
      const res = await $`${PYTHON} ${CODEMAP} scan --repo ${directory} --json - --compact`
        .cwd(directory).quiet().nothrow();
      if (res.exitCode !== 0) {
        // no es un repo git u otro error: no molestar
        log("scan falló", res.exitCode, res.stderr.toString().slice(0, 300));
        return null;
      }
      return JSON.parse(res.stdout.toString());
    } catch (error) {
      log("scan error", String(error));
      return null;
    }
  }

  const key = (change) => `${change.id}@${change.huella}`;

  function nudgeText(pending, missingTask) {
    const lines = pending.slice(0, MAX_LISTED).map((c) => {
      const state = c.estado_anotacion === "desactualizado" ? " (anotación desactualizada)" : "";
      return `- ${c.id}${state}: ${c.resumen}`;
    });
    if (pending.length > MAX_LISTED) lines.push(`- … y ${pending.length - MAX_LISTED} más`);
    const text = [
      `[Codemap] Esta sesión dejó ${pending.length} ${pending.length === 1 ? "cambio" : "cambios"} sin anotar:`,
      ...lines,
    ];
    if (missingTask) text.push("Tampoco hay descripción de la tarea ('tarea').");
    text.push(
      "",
      "Carga la skill `codemap-annotate` y anota estos cambios antes de terminar " +
        "(usa \"autor\": \"opencode\"). Si alguno no lo hiciste a propósito, dilo en su anotación.",
    );
    return text.join("\n");
  }

  return {
    // Primer mensaje de la sesión principal: foto de lo que ya estaba cambiado.
    "chat.message": async (input) => {
      const id = input.sessionID;
      if (baselines.has(id) || (await isSubagent(id))) return;
      const data = await scan();
      baselines.set(id, data ? new Set(data.cambios.map(key)) : null);
      log("foto inicial", id, data ? data.cambios.length : "sin repo");
    },

    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      const id = event.properties?.sessionID;
      if (!id || (await isSubagent(id))) return;
      const baseline = baselines.get(id);
      if (!baseline) return; // sesión anterior al plugin o fuera de un repo git

      const data = await scan();
      if (!data) return;
      const pending = data.cambios.filter(
        (c) => c.estado_anotacion !== "anotado" && !baseline.has(key(c)),
      );
      log("idle", id, "pendientes:", pending.map((c) => c.id));
      if (!pending.length) return;

      const state = nudges.get(id) ?? { count: 0, key: "" };
      const pendingKey = pending.map(key).sort().join("|");
      if (state.count >= MAX_NUDGES || state.key === pendingKey) return;
      nudges.set(id, { count: state.count + 1, key: pendingKey });

      try {
        const res = await client.session.promptAsync({
          path: { id },
          body: { parts: [{ type: "text", text: nudgeText(pending, !data.tarea) }] },
        });
        log("aviso enviado", id, res?.error ?? "ok");
      } catch (error) {
        log("aviso rechazado", id, String(error)); // no hay nada más que hacer
      }
    },
  };
};
