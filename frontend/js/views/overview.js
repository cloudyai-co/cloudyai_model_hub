/** Overview: the front page. A statement, a live-looking specimen sheet, a data band,
 *  two instrument rows with real document fragments, and margin notes. */

import { getJson } from "../api.js";
import { completenessRuler } from "../components/ruler.js";
import { handNote, levelBadge, linkButton, textLink } from "../components/ui.js";
import { clear, h, svg } from "../dom.js";
import { routeHref } from "../router.js";

/** Fixed, illustrative values. They are not read from any model. */
const SPECIMEN = {
  id: "example-org/example-7b",
  score: 84,
  level: "strong",
  stats: [
    ["Licence", "Apache-2.0"],
    ["Parameters", "7.62 B"],
    ["Files", "14 · 15.2 GB"],
    ["Digests", "SHA-256 × 4"],
    ["Access", "Open"],
  ],
};

const BAND = [
  ["12", "documentation checks, each weighted in the completeness score"],
  ["12", "accelerators in the hardware catalog, from T4 to MI300X"],
  ["10", "weight precisions, FP32 down to GGUF Q2_K"],
  ["200", "repository files per model, with SHA-256 where published"],
];

/** Corner crop marks, like a sheet that came off a press. Decorative only. */
function cropMarks() {
  return svg(
    "svg",
    {
      class: "crop-marks",
      viewBox: "0 0 100 100",
      preserveAspectRatio: "none",
      "aria-hidden": "true",
      focusable: "false",
    },
    svg("path", { d: "M0 6V0h6 M94 0h6v6 M100 94v6h-6 M6 100H0v-6", "vector-effect": "non-scaling-stroke" }),
  );
}

function statement() {
  return h(
    "section",
    { class: "statement", "aria-labelledby": "hero-title" },
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
  );
}

/** The specimen as an opened sheet under the statement, full width: the product is the hero. */
function openSheet() {
  return h(
    "figure",
    { class: "sheet-open", "aria-label": "Specimen datasheet, illustrative values" },
    cropMarks(),
    h(
      "figcaption",
      { class: "sheet-bar" },
      h("span", { class: "sheet-tag" }, "Specimen · illustrative, not live data"),
      h("span", { class: "mono sheet-id" }, SPECIMEN.id),
      levelBadge(SPECIMEN.level),
    ),
    h(
      "div",
      { class: "sheet-score" },
      h(
        "p",
        { class: "score-figure" },
        h("span", { class: "score-value" }, String(SPECIMEN.score)),
        h("span", { class: "score-of" }, "of 100"),
      ),
      completenessRuler(SPECIMEN.score, SPECIMEN.level),
    ),
    h(
      "dl",
      { class: "spec-strip" },
      SPECIMEN.stats.map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, value))),
    ),
    handNote(["The score reads the paperwork, not the model. A ", h("span", { class: "squig" }, "sparse card"), " can still hide a good one."], { small: true }),
  );
}

function dataBand() {
  return h(
    "section",
    { class: "band", "aria-label": "The system in numbers" },
    BAND.map(([value, caption]) =>
      h("div", {}, h("p", { class: "band-value" }, value), h("p", { class: "band-caption" }, caption)),
    ),
  );
}

/** A clipped fragment of the real datasheet: a few hairline rows, mono values. */
function aibomFragment() {
  const row = (label, value, note) =>
    h("div", { class: "frag-row" }, h("span", {}, label), h("span", { class: "mono" }, value), h("span", { class: "frag-note" }, note ?? ""));
  return h(
    "div",
    { class: "frag", "aria-hidden": "true" },
    cropMarks(),
    h("p", { class: "frag-tag" }, "From the document · section 02, licence"),
    row("Licence", "apache-2.0", "SPDX identifier"),
    row("Parameters", "7,615,616,512", "safetensors"),
    row("Files", "14 · 15,242,807,270 B", "4 × LFS"),
    h("div", { class: "frag-row frag-check is-present" }, h("span", {}, "Intended use"), h("span", { class: "mono" }, "documented · +12")),
    h("div", { class: "frag-row frag-check is-missing" }, h("span", {}, "Ethical considerations"), h("span", { class: "mono" }, "missing · 0")),
  );
}

/** A clipped fragment of the capacity view: the stacked bar and three accelerator rows. */
function capacityFragment() {
  const parts = [
    ["seg-weights", 82],
    ["seg-kv", 3],
    ["seg-act", 8],
    ["seg-fw", 7],
  ];
  const bar = h(
    "div",
    { class: "stack-bar" },
    parts.map(([className, width]) => {
      const segment = h("span", { class: className });
      segment.style.width = `${width}%`;
      return segment;
    }),
  );
  const row = (name, gpus, tokens) =>
    h("div", { class: "frag-row" }, h("span", {}, name), h("span", { class: "mono" }, `${gpus} GPU`), h("span", { class: "mono" }, `${tokens} tok/s`));
  return h(
    "div",
    { class: "frag", "aria-hidden": "true" },
    cropMarks(),
    h("p", { class: "frag-tag" }, "From the estimate · 7.62 B at FP16, 4096 context"),
    h("p", { class: "frag-total" }, "17.3 GB"),
    bar,
    h("div", { class: "frag-legend" }, ["Weights", "KV cache", "Activations", "Framework"].map((label, index) => h("span", {}, h("span", { class: `swatch ${parts[index][0]}` }), label))),
    row("NVIDIA H200", 1, 338),
    row("NVIDIA A100 80GB", 1, 141),
    row("NVIDIA T4", 2, 45),
  );
}

function instrument({ number, title, copy, outputs, href, linkLabel, fragment, flip = false }) {
  const text = h(
    "div",
    { class: "instrument-copy" },
    h("h3", {}, title),
    h("p", {}, copy),
    h("ul", {}, outputs.map((line) => h("li", {}, line))),
    textLink(linkLabel, href),
  );
  return h(
    "section",
    { class: `instrument ${flip ? "instrument-flip" : ""}`.trim(), "aria-label": `${number} ${title}` },
    h(
      "p",
      { class: "instrument-index" },
      h("span", { class: "section-num", "aria-hidden": "true" }, number),
    ),
    flip ? h("div", { class: "instrument-grid" }, fragment, text) : h("div", { class: "instrument-grid" }, text, fragment),
  );
}

function instruments() {
  return h(
    "div",
    { class: "instruments" },
    instrument({
      number: "01",
      title: "The AIBOM",
      copy:
        "Read the model card, configuration and file tree. Get a CycloneDX 1.6 ML-BOM with licence data, " +
        "SHA-256 digests for large files, and a completeness score that shows exactly what is missing.",
      outputs: ["CycloneDX 1.6 JSON, downloadable", "PDF report with the JSON attached", "Completeness checklist, item by item"],
      href: routeHref("aibom"),
      linkLabel: "Open the AIBOM generator",
      fragment: aibomFragment(),
    }),
    instrument({
      number: "02",
      title: "Model selection",
      copy:
        "Search Hugging Face, then estimate weight and KV-cache memory across precisions and context lengths. " +
        "See which accelerators fit, how many, and how hard the model is to operate — with the reasons in writing.",
      outputs: ["Memory by precision and context length", "Fit for twelve accelerators", "Operational complexity, explained"],
      href: routeHref("selection"),
      linkLabel: "Open model selection",
      fragment: capacityFragment(),
      flip: true,
    }),
  );
}

const FIELD_NOTES = [
  [
    "Why this exists",
    "We kept pasting model cards into review documents and re-checking licences by hand, one spreadsheet at a time. This tool is that margin work, done properly and kept up to date.",
  ],
  [
    "Nothing to sign",
    "Public models need no account and no key. The server reads the same public page you could open yourself, stores nothing between visits and downloads nothing. A token only unlocks gated models, and only if you choose to set one.",
  ],
  [
    "The keepable copy",
    "The PDF travels with the CycloneDX JSON stapled inside it, so the report and the data never drift apart. Print it, attach it, archive it.",
  ],
];

/** Margin notes as a letter: a sticky rail on the left, the notes flowing on the right. */
function fieldNotes() {
  return h(
    "section",
    { class: "fieldnotes", "aria-labelledby": "notes-title" },
    h(
      "div",
      { class: "fieldnotes-rail" },
      h("span", { class: "section-num", "aria-hidden": "true" }, "03"),
      h("h2", { id: "notes-title", class: "section-title" }, "Margin notes"),
    ),
    h(
      "div",
      { class: "fieldnotes-body" },
      FIELD_NOTES.map(([title, body]) =>
        h(
          "div",
          { class: "fieldnote" },
          h("p", { class: "fieldnote-title" }, title),
          h("p", { class: "hand" }, body),
        ),
      ),
      h("p", { class: "hand fieldnotes-sig" }, "— KhanKindle"),
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
  clear(root).append(statement(), openSheet(), dataBand(), instruments(), fieldNotes(), serviceLine());
}
