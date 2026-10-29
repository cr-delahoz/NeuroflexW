(function () {
  "use strict";

  var VIEWPORT_MARGIN = 8;

  var openDetails = null;
  var scrollResizeHandler = null;

  function positionMenu(details) {
    var summary = details.querySelector("summary");
    var menu = details.querySelector("[data-actions-menu]");
    if (!summary || !menu) {
      return;
    }

    var summaryRect = summary.getBoundingClientRect();
    var menuRect = menu.getBoundingClientRect();

    var left = summaryRect.right - menuRect.width;
    if (left < VIEWPORT_MARGIN) {
      left = VIEWPORT_MARGIN;
    }
    if (left + menuRect.width > window.innerWidth - VIEWPORT_MARGIN) {
      left = window.innerWidth - menuRect.width - VIEWPORT_MARGIN;
    }

    var top = summaryRect.bottom + VIEWPORT_MARGIN;
    if (top + menuRect.height > window.innerHeight - VIEWPORT_MARGIN) {
      top = summaryRect.top - menuRect.height - VIEWPORT_MARGIN;
    }
    if (top < VIEWPORT_MARGIN) {
      top = VIEWPORT_MARGIN;
    }

    menu.style.top = top + "px";
    menu.style.left = left + "px";
  }

  function detachOpenListeners() {
    if (scrollResizeHandler) {
      window.removeEventListener("scroll", scrollResizeHandler, true);
      window.removeEventListener("resize", scrollResizeHandler);
      scrollResizeHandler = null;
    }
    document.removeEventListener("click", handleOutsideClick, true);
    document.removeEventListener("keydown", handleEscape);
  }

  function closeDetails(details) {
    details.removeAttribute("open");
  }

  function handleOutsideClick(event) {
    if (openDetails && !openDetails.contains(event.target)) {
      closeDetails(openDetails);
    }
  }

  function handleEscape(event) {
    if (event.key === "Escape" && openDetails) {
      closeDetails(openDetails);
    }
  }

  document.addEventListener(
    "toggle",
    function (event) {
      var details = event.target;
      if (!(details instanceof Element) || !details.matches("[data-row-actions]")) {
        return;
      }

      if (openDetails && openDetails !== details) {
        closeDetails(openDetails);
      }

      if (details.open) {
        openDetails = details;
        detachOpenListeners();

        requestAnimationFrame(function () {
          positionMenu(details);
        });

        scrollResizeHandler = function () {
          requestAnimationFrame(function () {
            positionMenu(details);
          });
        };
        window.addEventListener("scroll", scrollResizeHandler, { passive: true, capture: true });
        window.addEventListener("resize", scrollResizeHandler, { passive: true });
        document.addEventListener("click", handleOutsideClick, true);
        document.addEventListener("keydown", handleEscape);
      } else if (openDetails === details) {
        openDetails = null;
        detachOpenListeners();
      }
    },
    true
  );
})();
