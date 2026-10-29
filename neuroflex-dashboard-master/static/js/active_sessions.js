(function () {
  "use strict";

  var POLL_INTERVAL_MS = 15000;
  var previousSessionIds = [];

  function formatCreatedAt(isoString) {
    if (!isoString) {
      return "No disponible";
    }
    var parsed = new Date(isoString);
    if (isNaN(parsed.getTime())) {
      return "No disponible";
    }
    return parsed.toLocaleString();
  }

  function renderSessions(container, sessions) {
    if (!sessions.length) {
      container.innerHTML =
        '<p class="text-sm text-slate-500">No tienes sesiones activas en este momento.</p>';
      return;
    }

    var items = sessions
      .map(function (session) {
        return (
          '<div class="rounded-2xl border border-border bg-mist px-4 py-4">' +
          '<div class="flex items-center justify-between gap-3">' +
          '<span class="font-semibold text-ink-900">' +
          session.session_id +
          "</span>" +
          '<span class="inline-flex items-center rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-success">● Confirmado</span>' +
          "</div>" +
          '<span class="mt-1 block text-sm text-slate-600">Codigo: ' +
          (session.display_code || "No disponible") +
          "</span>" +
          '<span class="mt-1 block text-sm text-slate-600">Iniciada: ' +
          formatCreatedAt(session.created_at) +
          "</span>" +
          '<span class="mt-1 block text-sm text-slate-600">Usuario VR: ' +
          (session.vr_user_email || "No disponible") +
          "</span>" +
          "</div>"
        );
      })
      .join("");

    container.innerHTML = items;
  }

  function pollActiveSessions(container) {
    var url = container.getAttribute("data-active-sessions-url");
    if (!url) {
      return;
    }

    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("active sessions request failed");
        }
        return response.json();
      })
      .then(function (data) {
        var currentSessions = data.active_sessions || [];
        var currentSessionIds = currentSessions.map(function (session) {
          return session.session_id;
        });

        if (previousSessionIds.length > 0) {
          var hasMissingSession = previousSessionIds.some(function (id) {
            return currentSessionIds.indexOf(id) === -1;
          });
          if (hasMissingSession) {
            // A previously active session disappeared (e.g. moved to
            // completed): reload the page so history updates too.
            window.location.reload();
            return;
          }
        }

        previousSessionIds = currentSessionIds;
        renderSessions(container, currentSessions);
      })
      .catch(function () {
        // Keep the last known list visible instead of showing an alarming error.
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var container = document.getElementById("active-sessions-list");
    if (!container) {
      return;
    }

    pollActiveSessions(container);
    setInterval(function () {
      pollActiveSessions(container);
    }, POLL_INTERVAL_MS);
  });
})();
