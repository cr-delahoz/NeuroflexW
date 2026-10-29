(function () {
  "use strict";

  var pollTimer = null;
  var cancelled = false;
  var updateStarted = false;

  function init() {
    if (sessionStorage.getItem("nf_update_checked")) return;
    sessionStorage.setItem("nf_update_checked", "1");

    fetch("/updater/check/")
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.has_update) return;
        showModal(data);
      })
      .catch(function () { });
  }

  function showModal(data) {
    var modal = document.getElementById("nf-update-modal");
    if (!modal) return;

    var versionEl = document.getElementById("nf-update-version");
    var changelogEl = document.getElementById("nf-update-changelog");
    if (versionEl) versionEl.textContent = data.version;
    if (changelogEl) changelogEl.textContent = data.changelog;

    modal.classList.remove("hidden");
    cancelled = false;

    var laterBtn = document.getElementById("nf-update-later");
    var applyBtn = document.getElementById("nf-update-apply");

    if (laterBtn) {
      laterBtn.addEventListener("click", function () {
        if (updateStarted) {
          var statusEl = document.getElementById("nf-update-status");
          if (statusEl) {
            statusEl.textContent = "La actualización continuará en segundo plano. La aplicación se cerrará para completar la instalación.";
          }
          var progressSection = document.getElementById("nf-update-progress");
          if (progressSection) progressSection.classList.remove("hidden");
          laterBtn.disabled = true;
          return;
        }
        cancelled = true;
        stopPolling();
        modal.classList.add("hidden");
      });
    }

    if (applyBtn) {
      applyBtn.addEventListener("click", function () {
        startUpdate(applyBtn, laterBtn, modal);
      });
    }
  }

  function startUpdate(applyBtn, laterBtn, modal) {
    updateStarted = true;
    applyBtn.disabled = true;

    var progressSection = document.getElementById("nf-update-progress");
    var progressBar = document.getElementById("nf-update-progress-bar");
    var statusEl = document.getElementById("nf-update-status");

    if (progressSection) progressSection.classList.remove("hidden");
    if (statusEl) statusEl.textContent = "Iniciando actualización…";

    fetch("/updater/run/", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() }
    })
      .then(function (response) {
        if (cancelled) return null;
        if (!response.ok) {
          if (statusEl) statusEl.textContent = "Error al iniciar la actualización (código " + response.status + ").";
          applyBtn.disabled = false;
          updateStarted = false;
          return null;
        }
        return response.json();
      })
      .then(function (data) {
        if (data === null || cancelled) return;
        if (data.status === "error") {
          if (statusEl) statusEl.textContent = data.message || "Error al iniciar la actualización.";
          applyBtn.disabled = false;
          updateStarted = false;
          return;
        }
        var jobId = data.job_id;
        schedulePoll(jobId, applyBtn, laterBtn, progressBar, statusEl);
      })
      .catch(function () {
        if (cancelled) return;
        if (statusEl) statusEl.textContent = "Error de conexión al iniciar la actualización.";
        applyBtn.disabled = false;
        updateStarted = false;
      });
  }

  function schedulePoll(jobId, applyBtn, laterBtn, progressBar, statusEl) {
    if (cancelled) return;
    pollTimer = setTimeout(function () {
      pollProgress(jobId, applyBtn, laterBtn, progressBar, statusEl);
    }, 500);
  }

  function pollProgress(jobId, applyBtn, laterBtn, progressBar, statusEl) {
    if (cancelled) return;
    fetch("/updater/progress/" + encodeURIComponent(jobId) + "/")
      .then(function (response) {
        if (cancelled) return null;
        if (!response.ok) {
          stopPolling();
          if (statusEl) statusEl.textContent = "Error al consultar el progreso (código " + response.status + ").";
          applyBtn.disabled = false;
          updateStarted = false;
          return null;
        }
        return response.json();
      })
      .then(function (data) {
        if (data === null || cancelled) return;

        if (data.percentage !== null && data.percentage !== undefined) {
          progressBar.value = data.percentage;
        } else {
          progressBar.removeAttribute("value");
        }

        if (statusEl) statusEl.textContent = data.message || "";

        if (data.status === "ready" || data.status === "done") {
          stopPolling();
          if (statusEl) statusEl.textContent = "La aplicación se cerrará para completar la instalación.";
        } else if (data.status === "error") {
          stopPolling();
          applyBtn.disabled = false;
          updateStarted = false;
        } else {
          schedulePoll(jobId, applyBtn, laterBtn, progressBar, statusEl);
        }
      })
      .catch(function () {
        if (cancelled) return;
        stopPolling();
        if (statusEl) statusEl.textContent = "Error de conexión al consultar el progreso.";
        applyBtn.disabled = false;
        updateStarted = false;
      });
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function getCsrfToken() {
    var cookie = document.cookie.split(";").find(function (c) {
      return c.trim().startsWith("csrftoken=");
    });
    return cookie ? cookie.split("=")[1] : "";
  }

  document.addEventListener("DOMContentLoaded", init);
})();
