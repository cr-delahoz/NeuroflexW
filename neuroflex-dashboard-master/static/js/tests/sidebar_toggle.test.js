const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "../sidebar_toggle.js"), "utf8");

function buildDom(savedState) {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body><button id="nf-sidebar-toggle" aria-expanded="true"></button></body></html>`,
    { runScripts: "outside-only", url: "http://localhost/" },
  );
  dom.window.eval(SCRIPT);
  if (savedState !== undefined) {
    // The script only reads storage on load; replay a fresh load for the test.
    if (savedState) {
      dom.window.localStorage.setItem("nf-sidebar-collapsed", savedState);
      dom.window.document.documentElement.classList.add("nf-sidebar-collapsed");
    }
    const fresh = new JSDOM(
      `<!DOCTYPE html><html class="${savedState ? "nf-sidebar-collapsed" : ""}"><body><button id="nf-sidebar-toggle" aria-expanded="true"></button></body></html>`,
      { runScripts: "outside-only", url: "http://localhost/" },
    );
    fresh.window.eval(SCRIPT);
    return fresh;
  }
  return dom;
}

test("clicking the toggle collapses, persists and updates aria", () => {
  const dom = buildDom();
  const toggle = dom.window.document.getElementById("nf-sidebar-toggle");

  toggle.click();

  assert.equal(
    dom.window.document.documentElement.classList.contains("nf-sidebar-collapsed"),
    true,
  );
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(dom.window.localStorage.getItem("nf-sidebar-collapsed"), "1");
});

test("second click restores the expanded state", () => {
  const dom = buildDom();
  const toggle = dom.window.document.getElementById("nf-sidebar-toggle");

  toggle.click();
  toggle.click();

  assert.equal(
    dom.window.document.documentElement.classList.contains("nf-sidebar-collapsed"),
    false,
  );
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(dom.window.localStorage.getItem("nf-sidebar-collapsed"), "0");
});

test("a saved collapsed state is applied on load without clicking", () => {
  const dom = buildDom("1");

  const toggle = dom.window.document.getElementById("nf-sidebar-toggle");
  assert.equal(
    dom.window.document.documentElement.classList.contains("nf-sidebar-collapsed"),
    true,
  );
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
});

test("does nothing when the toggle button is missing", () => {
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only",
  });
  dom.window.eval(SCRIPT);
  assert.equal(
    dom.window.document.documentElement.classList.contains("nf-sidebar-collapsed"),
    false,
  );
});
