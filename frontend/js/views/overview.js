/** Overview: what the hub does, the two tools, and whether the API is reachable. */

import { getJson } from "../api.js";
import { completenessRuler } from "../components/ruler.js";
import { linkButton, levelBadge, textLink } from "../components/ui.js";
import { clear, h } from "../dom.js";
import { routeHref } from "../router.js";

/** Fixed, illustrative values. They are not read from any model. */
const SPECIMEN_ROWS = [
  ["Licence", "Apache-2.0"],
  ["Access", "Open"],
  ["Parameters", "7.62 B, from safetensors"],
  ["Files", "14 files, 15.2 GB"],
  ["Digests", "SHA-256 for four weight shards"],
];

function specimen() {
  return h(
    "figure",
    { class: "specimen" },
    h("figcaption", { class: "specimen-caption" }, "Illustrative example, not live data"),
    h(
      "div",
      { class: "specimen-head" },
      h("p", { class: "specimen-title" }, "example-org/example-7b"),
      levelBadge("strong"),
    ),
    h(
      "div",
      { class: "score-figure" },
      h("span", { class: "score-value" }, "84"),
      h("span", { class: "score-of" }, "of 100"),
    ),
    completenessRuler(84, "strong"),
    h(
      "dl",
      { class: "specimen-rows" },
      SPECIMEN_ROWS.map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, value))),
    ),
  );
}

function hero() {
  return h(
    "section",
    { class: "hero", "aria-labelledby": "hero-title" },
    h(
      "div",
      { class: "hero-copy" },
      h(
        "p",
        { class: "eyebrow" },
        h("span", { class: "dot", "aria-hidden": "true" }),
        "Engineering reference · Hugging Face models",
      ),
      h(
        "h1",
        { class: "display", id: "hero-title" },
        "A datasheet for every model you ship. ",
        h("span", { class: "display-sub" }, "Before it reaches production."),
      ),
      h(
        "p",
        { class: "lede" },
        "Generate a CycloneDX 1.6 AI Bill of Materials and a printable PDF for any public Hugging Face model. " +
          "Then estimate what the model needs to run: memory, hardware and operational complexity.",
      ),
      h(
        "div",
        { class: "actions" },
        linkButton("Generate an AIBOM", routeHref("aibom"), { variant: "primary", iconName: "arrow" }),
        linkButton("Estimate capacity", routeHref("selection"), { iconName: "arrow" }),
      ),
    ),
    specimen(),
  );
}

function entry({ number, title, body, outputs, href, linkLabel }) {
  return h(
    "article",
    { class: "entry" },
    h("p", { class: "entry-num" }, number),
    h("h2", {}, title),
    h("p", {}, body),
    h(
      "ul",
      {},
      outputs.map((line) => h("li", {}, line)),
    ),
    textLink(linkLabel, href),
  );
}

function entries() {
  return h(
    "section",
    { class: "section", "aria-labelledby": "tools-title" },
    h("h2", { id: "tools-title", class: "sr-only" }, "Tools"),
    h(
      "div",
      { class: "entries" },
      entry({
        number: "01",
        title: "AIBOM",
        body:
          "Read the model card, configuration and file tree. Get a CycloneDX 1.6 ML-BOM with licence data, " +
          "SHA-256 digests for large files, and a completeness score that shows what is missing.",
        outputs: ["CycloneDX 1.6 JSON, downloadable", "PDF report with the JSON attached", "Completeness checklist"],
        href: routeHref("aibom"),
        linkLabel: "Open the AIBOM generator",
      }),
      entry({
        number: "02",
        title: "Model selection",
        body:
          "Search Hugging Face, then estimate weight and KV-cache memory across precisions and context lengths. " +
          "See which accelerators fit and how hard the model is to operate.",
        outputs: [
          "Memory by precision and context length",
          "Fit for twelve accelerators",
          "Operational complexity, with reasons",
        ],
        href: routeHref("selection"),
        linkLabel: "Open model selection",
      }),
    ),
  );
}

function serviceLine() {
  const state = h("span", { class: "dot-state", dataset: { state: "checking" }, "aria-hidden": "true" });
  const label = h("span", {}, "Checking the API");
  const line = h("p", { class: "service", role: "status" }, state, label);
  getJson("health")
    .then((health) => {
      state.dataset.state = "ok";
      label.textContent = `API online · version ${health.version}`;
    })
    .catch(() => {
      state.dataset.state = "down";
      label.textContent = "API unreachable. Check the deployment or your network.";
    });
  return line;
}

export function renderOverview(root) {
  clear(root).append(hero(), entries(), serviceLine());
}
