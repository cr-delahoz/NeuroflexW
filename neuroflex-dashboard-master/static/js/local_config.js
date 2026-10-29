function buildPayload(fields) {
  var payload = {
    NEUROFLEX_API_BASE_URL: fields.baseUrl.trim(),
    COGNITO_CLIENT_ID: fields.clientId.trim(),
  };
  if (fields.tokenInputVisible && fields.tokenValue.trim()) {
    payload.GITHUB_TOKEN = fields.tokenValue.trim();
  }
  return payload;
}

function isStaleResponse(requestGeneration, currentGeneration) {
  return requestGeneration !== currentGeneration;
}

function shouldMarkTokenDirty(eventType) {
  return eventType === "input";
}

(function () {
  "use strict";

  if (typeof window === "undefined") return;

  var SPINNER = '<svg data-loading-spinner="true" class="h-5 w-5 animate-spin text-current" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path></svg>';
  var modal = document.getElementById("local-config-modal");
  var openButton = document.getElementById("local-config-open");
  var closeButton = document.getElementById("local-config-close");
  var cancelButton = document.getElementById("local-config-cancel");
  var form = document.getElementById("local-config-form");
  var message = document.getElementById("local-config-message");
  var badge = document.getElementById("api-health-badge");
  var saveButton = document.getElementById("local-config-save");
  var tokenMaskedDisplay = document.getElementById("github-token-masked");
  var changeTokenButton = document.getElementById("github-token-change");
  var tokenInput = document.getElementById("id_github_token");
  var modalOpen = false;
  var configLoaded = false;
  var modalGeneration = 0;
  var healthCheckGeneration = 0;
  var configRequestGeneration = 0;
  var saveGeneration = 0;
  var tokenDirty = false;

  if (!modal || !openButton || !form) return;

  function setFieldsDisabled(disabled) {
    form.querySelectorAll("input").forEach(function (element) {
      element.disabled = disabled;
    });
    saveButton.disabled = disabled;
  }

  function restoreSaveButton() {
    saveButton.innerHTML = saveButton.getAttribute("data-ui-original-html") || "Guardar";
    saveButton.removeAttribute("data-ui-original-html");
    saveButton.disabled = false;
    saveButton.removeAttribute("aria-busy");
  }

  function resetTokenEdit() {
    tokenDirty = false;
    tokenMaskedDisplay.classList.remove("hidden");
    tokenMaskedDisplay.setAttribute("aria-hidden", "false");
    changeTokenButton.classList.remove("hidden");
    tokenInput.classList.add("hidden");
    tokenInput.setAttribute("aria-hidden", "true");
    tokenInput.value = "";
  }

  function showTokenEdit() {
    tokenMaskedDisplay.classList.add("hidden");
    tokenMaskedDisplay.setAttribute("aria-hidden", "true");
    changeTokenButton.classList.add("hidden");
    tokenInput.classList.remove("hidden");
    tokenInput.setAttribute("aria-hidden", "false");
    tokenInput.focus();
  }

  function focusableModalElements() {
    return Array.from(modal.querySelectorAll('button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])')).filter(function (element) {
      return !element.disabled && !element.classList.contains("hidden") && element.getAttribute("aria-hidden") !== "true";
    });
  }

  changeTokenButton.addEventListener("click", showTokenEdit);
  tokenInput.addEventListener("input", function () {
    if (shouldMarkTokenDirty("input")) tokenDirty = true;
  });

  function csrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function showMessage(text, isError) {
    message.textContent = text;
    message.classList.remove("hidden");
    message.classList.toggle("bg-emerald-50", !isError);
    message.classList.toggle("text-success", !isError);
    message.classList.toggle("border-emerald-200", !isError);
    message.classList.toggle("bg-rose-50", isError);
    message.classList.toggle("text-danger", isError);
    message.classList.toggle("border-rose-200", isError);
    message.classList.toggle("border", true);
  }

  function setBadge(state, label) {
    badge.setAttribute("data-state", state);
    badge.querySelector("[data-label]").textContent = label;
    badge.querySelector("[data-dot]").className = "h-2 w-2 rounded-full " + (state === "ok" ? "bg-emerald-500" : state === "error" ? "bg-rose-500" : "bg-slate-400");
  }

  function runHealthCheck() {
    healthCheckGeneration += 1;
    var requestGeneration = healthCheckGeneration;
    setBadge("checking", "Verificando…");
    return fetch("/api-health/", { headers: { "Accept": "application/json" } })
      .then(function (response) {
        if (response.status === 403) throw new Error("Acceso no permitido.");
        return response.json();
      })
      .then(function (data) {
        if (isStaleResponse(requestGeneration, healthCheckGeneration)) return;
        setBadge(data.available ? "ok" : "error", data.available ? "Disponible" : "No disponible");
      })
      .catch(function () {
        if (!isStaleResponse(requestGeneration, healthCheckGeneration)) setBadge("error", "No disponible");
      });
  }

  function openModal() {
    if (modalOpen) return;
    modalOpen = true;
    configLoaded = false;
    modalGeneration += 1;
    var requestGeneration = modalGeneration;
    configRequestGeneration += 1;
    var configRequestToken = configRequestGeneration;
    resetTokenEdit();
    modal.showModal();
    var firstFocusable = focusableModalElements()[0];
    if (firstFocusable) firstFocusable.focus();
    message.classList.add("hidden");
    setFieldsDisabled(true);
    runHealthCheck();
    fetch("/local-config/", { headers: { "Accept": "application/json" } })
      .then(function (response) {
        if (response.status === 403) throw new Error("Acceso no permitido.");
        if (!response.ok) throw new Error("No fue posible cargar la configuración.");
        return response.json();
      })
      .then(function (data) {
        if (!modalOpen || isStaleResponse(requestGeneration, modalGeneration) || isStaleResponse(configRequestToken, configRequestGeneration) || configLoaded) return;
        document.getElementById("id_neuroflex_api_base_url").value = data.NEUROFLEX_API_BASE_URL || "";
        document.getElementById("id_cognito_client_id").value = data.COGNITO_CLIENT_ID || "";
        tokenMaskedDisplay.textContent = data.GITHUB_TOKEN || "";
        configLoaded = true;
      })
      .catch(function (error) {
        if (modalOpen && !isStaleResponse(requestGeneration, modalGeneration) && !isStaleResponse(configRequestToken, configRequestGeneration)) {
          showMessage(error.message || "No fue posible cargar la configuración.", true);
        }
      })
      .finally(function () {
        if (!isStaleResponse(requestGeneration, modalGeneration) && !isStaleResponse(configRequestToken, configRequestGeneration)) setFieldsDisabled(false);
      });
  }

  function closeModal() {
    if (!modal.open) return;
    modal.close();
  }

  function handleModalClose() {
    modalOpen = false;
    modalGeneration += 1;
    configRequestGeneration += 1;
    healthCheckGeneration += 1;
    saveGeneration += 1;
    restoreSaveButton();
    resetTokenEdit();
    openButton.focus();
  }
  openButton.addEventListener("click", openModal);
  closeButton.addEventListener("click", closeModal);
  cancelButton.addEventListener("click", closeModal);
  modal.addEventListener("close", handleModalClose);
  // Sin cierre por click fuera ni Escape: el modal solo se cierra con la X
  // o Cancelar, para evitar cierres accidentales al trabajar en el formulario.
  modal.addEventListener("keydown", function (event) {
    if (event.key !== "Tab") return;
    var focusable = focusableModalElements();
    if (!focusable.length) return;
    var currentIndex = focusable.indexOf(document.activeElement);
    var nextIndex = event.shiftKey
      ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
      : (currentIndex === focusable.length - 1 ? 0 : currentIndex + 1);
    event.preventDefault();
    focusable[nextIndex].focus();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    saveGeneration += 1;
    var requestSaveGeneration = saveGeneration;
    message.classList.add("hidden");
    var payload = buildPayload({
      baseUrl: document.getElementById("id_neuroflex_api_base_url").value,
      clientId: document.getElementById("id_cognito_client_id").value,
      tokenInputVisible: !tokenInput.classList.contains("hidden") && tokenDirty,
      tokenValue: tokenInput.value,
    });
    if (!saveButton.hasAttribute("data-ui-original-html")) {
      saveButton.setAttribute("data-ui-original-html", saveButton.innerHTML);
    }
    saveButton.innerHTML = SPINNER + '<span class="ml-2">Guardando…</span>';
    setFieldsDisabled(true);
    saveButton.setAttribute("aria-busy", "true");
    fetch("/local-config/", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }, body: JSON.stringify(payload) })
      .then(function (response) { return response.json().then(function (data) { return { status: response.status, ok: response.ok, data: data }; }); })
      .then(function (result) {
        if (isStaleResponse(requestSaveGeneration, saveGeneration)) return;
        if (!result.ok) {
          var fallback = result.status === 403 ? "Acceso no permitido." : result.status === 400 ? "Configuración inválida." : result.status >= 500 ? "Error del servidor." : "No fue posible guardar la configuración.";
          showMessage(result.data.error || fallback, true);
          return;
        }
        tokenMaskedDisplay.textContent = result.data.GITHUB_TOKEN || "";
        resetTokenEdit();
        showMessage("Configuración guardada correctamente.", false);
        return runHealthCheck();
      })
      .catch(function () {
        if (!isStaleResponse(requestSaveGeneration, saveGeneration)) showMessage("No fue posible guardar la configuración.", true);
      })
      .finally(function () {
        if (!isStaleResponse(requestSaveGeneration, saveGeneration)) {
          setFieldsDisabled(false);
          restoreSaveButton();
        }
      });
  });
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = { buildPayload, isStaleResponse, shouldMarkTokenDirty };
}
