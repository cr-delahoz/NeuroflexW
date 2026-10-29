(function () {
  "use strict";

  var STORAGE_KEY = "nf-sidebar-collapsed";
  var toggle = document.getElementById("nf-sidebar-toggle");
  if (!toggle) return;

  function isCollapsed() {
    return document.documentElement.classList.contains("nf-sidebar-collapsed");
  }

  function apply(collapsed, persist) {
    document.documentElement.classList.toggle("nf-sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "Desplegar el menu lateral" : "Plegar el menu lateral");
    toggle.setAttribute("title", collapsed ? "Desplegar el menu lateral" : "Plegar el menu lateral");
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
      } catch (error) {}
    }
  }

  // Reconcile aria attributes with the pre-paint class the head script set.
  apply(isCollapsed(), false);

  toggle.addEventListener("click", function () {
    apply(!isCollapsed(), true);
  });
})();
