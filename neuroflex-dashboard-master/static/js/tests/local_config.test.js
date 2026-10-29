const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const {
  buildPayload,
  isStaleResponse,
  shouldMarkTokenDirty,
} = require("../local_config.js");

test("omits GITHUB_TOKEN when the token input is not used", () => {
  assert.deepEqual(
    buildPayload({
      baseUrl: "https://api.example.com",
      clientId: "client-id",
      tokenInputVisible: false,
      tokenValue: "new-token",
    }),
    {
      NEUROFLEX_API_BASE_URL: "https://api.example.com",
      COGNITO_CLIENT_ID: "client-id",
    },
  );
});

test("identifies stale GET config responses", () => {
  assert.equal(isStaleResponse(1, 2), true);
  assert.equal(isStaleResponse(2, 2), false);
});

test("identifies stale health check responses", () => {
  assert.equal(isStaleResponse(3, 4), true);
  assert.equal(isStaleResponse(4, 4), false);
});

test("identifies stale POST save responses before a health check", () => {
  assert.equal(isStaleResponse(5, 6), true);
  assert.equal(isStaleResponse(6, 6), false);
});

test("does not mark the token dirty on focus", () => {
  assert.equal(shouldMarkTokenDirty("focus"), false);
  assert.equal(shouldMarkTokenDirty("input"), true);
});

const modalMarkup = fs.readFileSync(
  path.join(__dirname, "../../../templates/accounts/local_config_modal.html"),
  "utf8",
);

function response(data, status = 200) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => data,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((res) => { resolve = res; });
  return { promise, resolve };
}

async function loadDom(fetchMock) {
  const dom = new JSDOM(`<body><button id="local-config-open"></button>${modalMarkup}</body>`, { url: "http://localhost/" });
  if (!dom.window.HTMLDialogElement.prototype.showModal) {
    dom.window.HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
  }
  if (!dom.window.HTMLDialogElement.prototype.close) {
    dom.window.HTMLDialogElement.prototype.close = function () {
      this.open = false;
      this.dispatchEvent(new dom.window.Event("close"));
    };
  }
  global.window = dom.window;
  global.document = dom.window.document;
  global.fetch = fetchMock;
  delete require.cache[require.resolve("../local_config.js")];
  require("../local_config.js");
  return dom;
}

function unloadDom(dom) {
  dom.window.close();
  delete global.window;
  delete global.document;
  delete global.fetch;
  delete require.cache[require.resolve("../local_config.js")];
}

test("opening the modal requests the local configuration", async () => {
  const calls = [];
  const dom = await loadDom(async (url, options) => {
    calls.push({ url, options });
    return response({ available: true });
  });

  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("local-config-modal").open, true);
  assert.ok(calls.some((call) => call.url === "/local-config/" && (!call.options || !call.options.method || call.options.method === "GET")));
  unloadDom(dom);
});

test("a successful GET populates the configuration form", async () => {
  const dom = await loadDom(async (url) => url === "/local-config/"
    ? response({ NEUROFLEX_API_BASE_URL: "https://api.example", COGNITO_CLIENT_ID: "client", GITHUB_TOKEN: "••••" })
    : response({ available: true }));
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("id_neuroflex_api_base_url").value, "https://api.example");
  assert.equal(dom.window.document.getElementById("id_cognito_client_id").value, "client");
  unloadDom(dom);
});

test("the masked token display preserves the final four characters", async () => {
  const dom = await loadDom(async (url) => url === "/local-config/"
    ? response({ GITHUB_TOKEN: "••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••abcd" })
    : response({ available: true }));
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("github-token-masked").textContent.slice(-4), "abcd");
  unloadDom(dom);
});

test("Cambiar reveals the password input", async () => {
  const dom = await loadDom(async (url) => url === "/local-config/"
    ? response({})
    : response({ available: true }));
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("github-token-change").click();

  assert.equal(dom.window.document.getElementById("id_github_token").classList.contains("hidden"), false);
  unloadDom(dom);
});

test("saving sends a POST with the edited configuration", async () => {
  const calls = [];
  const dom = await loadDom(async (url, options) => {
    calls.push({ url, options });
    return url === "/local-config/"
      ? response({ NEUROFLEX_API_BASE_URL: "old", COGNITO_CLIENT_ID: "old" })
      : response({ available: true });
  });
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("id_neuroflex_api_base_url").value = " https://new.example ";
  dom.window.document.getElementById("id_cognito_client_id").value = " new-client ";
  dom.window.document.getElementById("github-token-change").click();
  const token = dom.window.document.getElementById("id_github_token");
  token.value = " new-token ";
  token.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  dom.window.document.getElementById("local-config-form").requestSubmit();
  await new Promise(setImmediate);

  const post = calls.find((call) => call.options && call.options.method === "POST");
  assert.ok(post);
  assert.deepEqual(JSON.parse(post.options.body), {
    NEUROFLEX_API_BASE_URL: "https://new.example",
    COGNITO_CLIENT_ID: "new-client",
    GITHUB_TOKEN: "new-token",
  });
  unloadDom(dom);
});

test("a successful save updates the masked token and hides the password input", async () => {
  const dom = await loadDom(async (url, options) => {
    if (options && options.method === "POST") return response({ GITHUB_TOKEN: "••••••••••••new4" });
    return url === "/local-config/" ? response({ GITHUB_TOKEN: "••••••••••••old4" }) : response({ available: true });
  });
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  const changeButton = dom.window.document.getElementById("github-token-change");
  changeButton.click();
  const token = dom.window.document.getElementById("id_github_token");
  token.value = "new-token";
  token.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  dom.window.document.getElementById("local-config-form").requestSubmit();
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("github-token-masked").textContent, "••••••••••••new4");
  assert.equal(token.classList.contains("hidden"), true);
  unloadDom(dom);
});

test("the save button is disabled and shows a spinner while saving", async () => {
  const save = deferred();
  const dom = await loadDom(async (url, options) => {
    if (options && options.method === "POST") return save.promise;
    return url === "/local-config/" ? response({}) : response({ available: true });
  });
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("local-config-form").requestSubmit();
  const saveButton = dom.window.document.getElementById("local-config-save");

  assert.equal(saveButton.disabled, true);
  assert.equal(saveButton.getAttribute("aria-busy"), "true");
  assert.ok(saveButton.querySelector("[data-loading-spinner]") || saveButton.innerHTML.includes("Guardando"));
  save.resolve(response({}));
  await new Promise(setImmediate);
  unloadDom(dom);
});

test("all form inputs are disabled while saving and restored when the current save finishes", async () => {
  const save = deferred();
  const dom = await loadDom(async (url, options) => {
    if (options && options.method === "POST") return save.promise;
    return url === "/local-config/" ? response({}) : response({ available: true });
  });
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("local-config-form").requestSubmit();

  const form = dom.window.document.getElementById("local-config-form");
  assert.deepEqual(
    Array.from(form.querySelectorAll("input")).map((input) => input.disabled),
    [true, true, true],
  );
  assert.equal(dom.window.document.getElementById("local-config-close").disabled, false);
  assert.equal(dom.window.document.getElementById("local-config-cancel").disabled, false);

  save.resolve(response({}));
  await new Promise(setImmediate);

  assert.deepEqual(
    Array.from(form.querySelectorAll("input")).map((input) => input.disabled),
    [false, false, false],
  );
  unloadDom(dom);
});

test("a stale save response does not re-enable fields for the current save", async () => {
  const saves = [];
  const dom = await loadDom(async (url, options) => {
    if (options && options.method === "POST") {
      const save = deferred();
      saves.push(save);
      return save.promise;
    }
    return url === "/local-config/" ? response({}) : response({ available: true });
  });
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  const form = dom.window.document.getElementById("local-config-form");
  form.requestSubmit();
  form.requestSubmit();

  saves[0].resolve(response({}));
  await new Promise(setImmediate);
  assert.equal(dom.window.document.getElementById("id_neuroflex_api_base_url").disabled, true);

  saves[1].resolve(response({}));
  await new Promise(setImmediate);
  assert.equal(dom.window.document.getElementById("id_neuroflex_api_base_url").disabled, false);
  unloadDom(dom);
});

test("concurrent saves restore the original button HTML after the current save finishes", async () => {
  const saves = [];
  const dom = await loadDom(async (url, options) => {
    if (options && options.method === "POST") {
      const save = deferred();
      saves.push(save);
      return save.promise;
    }
    return url === "/local-config/" ? response({}) : response({ available: true });
  });
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  const form = dom.window.document.getElementById("local-config-form");
  const saveButton = dom.window.document.getElementById("local-config-save");
  const originalHtml = saveButton.innerHTML;

  form.requestSubmit();
  form.requestSubmit();
  assert.equal(saveButton.getAttribute("data-ui-original-html"), originalHtml);

  saves[0].resolve(response({}));
  await new Promise(setImmediate);
  assert.notEqual(saveButton.innerHTML, originalHtml);

  saves[1].resolve(response({}));
  await new Promise(setImmediate);

  assert.equal(saveButton.innerHTML, originalHtml);
  assert.equal(saveButton.hasAttribute("data-ui-original-html"), false);
  unloadDom(dom);
});

test("backend validation errors are displayed in the message area", async () => {
  const dom = await loadDom(async (url, options) => options && options.method === "POST"
    ? response({ error: "NEUROFLEX_API_BASE_URL es obligatorio." }, 400)
    : url === "/local-config/" ? response({}) : response({ available: true }));
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("local-config-form").requestSubmit();
  await new Promise(setImmediate);

  const message = dom.window.document.getElementById("local-config-message");
  assert.equal(message.textContent, "NEUROFLEX_API_BASE_URL es obligatorio.");
  assert.equal(message.classList.contains("hidden"), false);
  unloadDom(dom);
});

test("server errors are displayed in the message area", async () => {
  const dom = await loadDom(async (url, options) => options && options.method === "POST"
    ? response({ error: "Servicio no disponible" }, 500)
    : url === "/local-config/" ? response({}) : response({ available: true }));
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  dom.window.document.getElementById("local-config-form").requestSubmit();
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("local-config-message").textContent, "Servicio no disponible");
  unloadDom(dom);
});

test("modal focus moves to the close button and returns to the trigger", async () => {
  const dom = await loadDom(async (url) => url === "/local-config/" ? response({}) : response({ available: true }));
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  assert.equal(dom.window.document.activeElement.id, "local-config-close");
  dom.window.document.getElementById("local-config-close").click();
  assert.equal(dom.window.document.activeElement, openButton);
  unloadDom(dom);
});

test("modal focus wraps with Tab and Shift+Tab", async () => {
  const dom = await loadDom(async (url) => url === "/local-config/" ? response({}) : response({ available: true }));
  dom.window.document.getElementById("local-config-open").click();
  await new Promise(setImmediate);
  const modal = dom.window.document.getElementById("local-config-modal");
  const cancel = dom.window.document.getElementById("local-config-cancel");
  const save = dom.window.document.getElementById("local-config-save");
  save.focus();
  modal.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
  assert.equal(dom.window.document.activeElement, dom.window.document.getElementById("local-config-close"));
  dom.window.document.getElementById("local-config-close").focus();
  modal.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
  assert.equal(dom.window.document.activeElement, save);
  unloadDom(dom);
});

test("a stale GET response does not overwrite a newer modal load", async () => {
  const requests = [];
  const dom = await loadDom((url) => {
    const request = deferred();
    requests.push({ url, request });
    return request.promise;
  });
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  dom.window.document.getElementById("local-config-close").click();
  assert.equal(dom.window.document.getElementById("local-config-modal").open, false);
  openButton.click();
  const configRequests = requests.filter(({ url }) => url === "/local-config/");
  configRequests[0].request.resolve(response({ NEUROFLEX_API_BASE_URL: "stale" }));
  configRequests[1].request.resolve(response({ NEUROFLEX_API_BASE_URL: "fresh" }));
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("id_neuroflex_api_base_url").value, "fresh");
  unloadDom(dom);
});

test("closing the modal invalidates an in-flight health check", async () => {
  const health = deferred();
  const dom = await loadDom((url) => url === "/api-health/" ? health.promise : Promise.resolve(response({})));
  const openButton = dom.window.document.getElementById("local-config-open");
  openButton.click();
  dom.window.document.getElementById("local-config-close").click();
  health.resolve(response({ available: true }));
  await new Promise(setImmediate);

  assert.equal(dom.window.document.getElementById("api-health-badge").dataset.state, "checking");
  unloadDom(dom);
});
