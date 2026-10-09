/**
 * Entry point. Wires the theme toggle, the hash router and the three views.
 * No framework and no build step: this file is loaded as an ES module by index.html.
 */

import { getJson } from "./api.js";
import { alertBox } from "./components/ui.js";
import { clear } from "./dom.js";
import { initTheme } from "./theme.js";
import { onRouteChange, startRouter } from "./router.js";
import { renderAibom } from "./views/aibom.js";
import { renderOverview } from "./views/overview.js";
import { renderSelection } from "./views/selection.js";

const BASE_TITLE = "CloudyAI Model Hub";
const VIEWS = {
  overview: renderOverview,
  aibom: renderAibom,
  selection: renderSelection,
};
const TITLES = {
  overview: "Overview",
  aibom: "AIBOM",
  selection: "Model selection",
};

const main = document.getElementById("main");
let controller = null;
let currentView = null;

/** Render a route. Each render cancels the requests of the previous one. */
function render({ name, params }) {
  controller?.abort();
  controller = new AbortController();

  for (const link of document.querySelectorAll(".nav a[data-route]")) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = name === "overview" ? BASE_TITLE : `${TITLES[name]} · ${BASE_TITLE}`;

  try {
    VIEWS[name](main, params, { signal: controller.signal });
  } catch (error) {
    console.error(error);
    clear(main).append(alertBox("This page could not be shown", "Reload the page. If the problem continues, report it."));
  }

  if (currentView !== name) {
    window.scrollTo({ top: 0, behavior: "instant" });
    main.focus({ preventScroll: true });
  }
  currentView = name;
}

async function showVersion() {
  try {
    const health = await getJson("health");
    document.getElementById("app-version").textContent = `v${health.version}`;
  } catch {
    // The footer simply stays without a version when the API is unreachable.
  }
}

initTheme(document.getElementById("theme-toggle"));
onRouteChange(render);
startRouter();
showVersion();
