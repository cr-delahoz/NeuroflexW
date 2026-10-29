// Ejecuta el plugin de opencode instalado contra un repo real con un cliente simulado.
// Uso: node opencode_harness.mjs <plugin.js> <repo> <pasos.json>
// Pasos: {"op":"message"|"idle","session":"root"|"child"} | {"op":"write","path","text"}
//        | {"op":"annotate","json":{...}}
// Imprime en stdout un JSON con los avisos que el plugin envió a opencode.
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const [pluginPath, repo, stepsPath] = process.argv.slice(2);
const steps = JSON.parse(readFileSync(stepsPath, "utf8"));

// Imitación mínima del shell de Bun: `$\`cmd ${arg}\`.cwd().quiet().nothrow()` y await.
function shell(strings, ...values) {
  const argv = [];
  strings.forEach((part, i) => {
    argv.push(...part.split(/\s+/).filter(Boolean));
    if (i < values.length) argv.push(String(values[i]));
  });
  let cwd;
  const run = () => {
    const r = spawnSync(argv[0], argv.slice(1), { cwd, env: process.env });
    return { exitCode: r.status, stdout: r.stdout, stderr: r.stderr };
  };
  const chain = {
    cwd(dir) { cwd = dir; return chain; },
    quiet() { return chain; },
    nothrow() { return chain; },
    then(ok, fail) { return Promise.resolve().then(run).then(ok, fail); },
  };
  return chain;
}

const parentIDs = { root: undefined, child: "root" };
const prompts = [];
const client = {
  session: {
    get: async ({ path }) => ({ data: { id: path.id, parentID: parentIDs[path.id] } }),
    promptAsync: async ({ path, body }) => { prompts.push({ session: path.id, text: body.parts[0].text }); return {}; },
  },
};

const mod = await import(pathToFileURL(pluginPath).href);
const hooks = await mod.CodemapPlugin({ client, $: shell, directory: repo });
const codemap = readFileSync(pluginPath, "utf8").match(/const CODEMAP = "(.*)";/)[1];
const python = readFileSync(pluginPath, "utf8").match(/const PYTHON = "(.*)";/)[1];

for (const step of steps) {
  if (step.op === "message") {
    await hooks["chat.message"]({ sessionID: step.session }, { message: {}, parts: [] });
  } else if (step.op === "idle") {
    await hooks.event({ event: { type: "session.idle", properties: { sessionID: step.session } } });
  } else if (step.op === "write") {
    const target = join(repo, step.path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, step.text);
  } else if (step.op === "annotate") {
    const file = join(process.env.CODEMAP_STORE, "input.json");
    mkdirSync(process.env.CODEMAP_STORE, { recursive: true });
    writeFileSync(file, JSON.stringify(step.json));
    spawnSync(python, [codemap, "annotate", "--repo", repo, file], { env: process.env });
  }
}
process.stdout.write(JSON.stringify(prompts));
