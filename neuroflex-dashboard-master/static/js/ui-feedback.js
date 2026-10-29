(function () {
  "use strict";

  var SPINNER = '<svg data-loading-spinner="true" class="h-5 w-5 animate-spin text-current" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path></svg>';

  function loadingText(control, owner) {
    return control.getAttribute("data-loading-text") || owner.getAttribute("data-loading-text") || "Procesando…";
  }

  function start(control, text) {
    if (!control || control.getAttribute("data-ui-loading") === "true") return;
    control.setAttribute("data-ui-loading", "true");
    control.setAttribute("data-ui-original-html", control.innerHTML);
    control.setAttribute("data-ui-was-disabled", control.disabled ? "true" : "false");
    control.innerHTML = SPINNER + '<span class="ml-2">' + text + "</span>";
    if ("disabled" in control) control.disabled = true;
    control.setAttribute("aria-busy", "true");
  }

  function restore(control) {
    if (!control || control.getAttribute("data-ui-loading") !== "true") return;
    control.innerHTML = control.getAttribute("data-ui-original-html") || "";
    if ("disabled" in control && control.getAttribute("data-ui-was-disabled") !== "true") control.disabled = false;
    control.removeAttribute("aria-busy");
    control.removeAttribute("data-ui-loading");
    control.removeAttribute("data-ui-original-html");
    control.removeAttribute("data-ui-was-disabled");
  }

  function submitControl(form) {
    return form.querySelector('button[type="submit"], input[type="submit"]');
  }

  document.addEventListener("submit", function (event) {
    if (event.defaultPrevented) return;
    var control = submitControl(event.target);
    if (control) start(control, loadingText(control, event.target));
  });

  function showDownloadToast() {
    var toast = document.getElementById("nf-download-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "nf-download-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      toast.className =
        "fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-ink-800 px-5 py-3 text-sm font-medium text-white shadow-lg transition-opacity duration-300";
      toast.style.opacity = "0";
      toast.style.pointerEvents = "none";
      document.body.appendChild(toast);
    }
    toast.textContent = "Descargando informe. Revisa tu carpeta de Descargas.";
    toast.style.opacity = "1";
    toast.style.pointerEvents = "auto";
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(function () {
      toast.style.opacity = "0";
      toast.style.pointerEvents = "none";
    }, 4000);
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented) return;
    var control = event.target.closest('[data-loading="true"]');
    if (control) {
      start(control, loadingText(control, control));
      if (control.tagName === "A") {
        var delay = (control.hasAttribute("download") || control.hasAttribute("target")) ? 1000 : 5000;
        setTimeout(function () { restore(control); }, delay);
      }
    }
    var downloadLink = event.target.closest("a[download]");
    if (downloadLink) {
      showDownloadToast();
    }
    var pageLink = event.target.closest('[data-pagination="true"] a');
    if (pageLink) start(pageLink, loadingText(pageLink, pageLink));
  });

  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll('[data-ui-loading="true"]').forEach(restore);
  });

  window.NeuroFlexUiFeedback = { start: start, restore: restore };
})();
