/** AIBOM generator: enter a model, read its datasheet, then download the PDF report or the JSON. */

import { ApiError, getJson } from "../api.js";
import { clear, h } from "../dom.js";
import { navigate } from "../router.js";
import { alertBox, button, chips, emptyNote, field, handNote, statusLine } from "../components/ui.js";
import { buildDatasheet } from "./datasheet.js";

export const EXAMPLE_MODELS = [
  "Qwen/Qwen2.5-7B-Instruct",
  "HuggingFaceH4/zephyr-7b-beta",
  "mistralai/Mixtral-8x7B-Instruct-v0.1",
];

const SECTIONS = ["Identity", "Licence", "Architecture", "Evaluation", "Considerations", "Files", "Document"];

function header() {
  return h(
    "header",
    { class: "page-head" },
    h("p", { class: "eyebrow" }, h("span", { class: "dot", "aria-hidden": "true" }), "01 · AIBOM generator"),
    h("h1", { class: "display" }, "Bill of materials for a model."),
    h(
      "p",
      { class: "lede" },
      "Paste a Hugging Face model id or link. The generator reads the public model card, configuration " +
        "and file tree, then assembles a CycloneDX 1.6 document and a printable PDF.",
    ),
  );
}

function modelForm(model) {
  const input = h("input", {
    id: "model-input",
    name: "model",
    class: "input input-mono input-lg",
    type: "text",
    value: model,
    placeholder: "org/model-name",
    autocomplete: "off",
    autocapitalize: "off",
    spellcheck: false,
    maxlength: 200,
    "aria-describedby": "model-input-hint",
  });
  const submit = button("Generate AIBOM", { variant: "primary", iconName: "arrow" });
  submit.type = "submit";

  const form = h(
    "form",
    {
      class: "form",
      onsubmit: (event) => {
        event.preventDefault();
        const value = input.value.trim();
        if (!value) {
          input.focus();
          return;
        }
        navigate("aibom", { model: value });
      },
    },
    h(
      "div",
      { class: "form-group" },
      h(
        "div",
        { class: "form-row" },
        field({ id: "model-input", label: "Model id or link", control: input, className: "model-field" }),
        submit,
      ),
      h(
        "p",
        { class: "field-hint", id: "model-input-hint" },
        "Accepts org/name or a huggingface.co model link. Public models need no token — if you can open " +
          "the page without signing in, this can read it. Datasets and Spaces are not supported.",
      ),
    ),
    chips("Try", EXAMPLE_MODELS, (value) => navigate("aibom", { model: value })),
  );
  return { form, input };
}

function tableOfContents() {
  return h(
    "ol",
    { class: "toc", "aria-label": "Sections in the datasheet" },
    SECTIONS.map((title, index) =>
      h(
        "li",
        {},
        h("span", { class: "toc-num" }, String(index + 1).padStart(2, "0")),
        h("span", {}, title),
      ),
    ),
  );
}

function idleState() {
  return h(
    "div",
    { class: "idle" },
    emptyNote(
      "Paste an id above and the datasheet appears in a second or two. Nothing is stored between " +
        "visits, and nothing is downloaded: the generator only reads what the Hub shows anyone.",
    ),
    handNote(["Close the tab and it is gone. Only ", h("span", { class: "squig" }, "the report you keep"), " remains."], { small: true }),
    tableOfContents(),
  );
}

async function load(model, region, signal) {
  region.replaceChildren(statusLine(`Reading the public page for ${model} — card, config and file list`, { busy: true }));
  try {
    const data = await getJson("aibom/generate", { model }, { signal });
    if (signal.aborted) return;
    region.replaceChildren(buildDatasheet(data));
  } catch (error) {
    if (signal.aborted) return;
    const message =
      error instanceof ApiError ? error.message : "Something unexpected went wrong. Try again in a moment.";
    region.replaceChildren(alertBox("The AIBOM could not be built", message));
  }
}

/** Route handler for #/aibom?model=... */
export function renderAibom(root, params, { signal }) {
  const model = (params.get("model") || "").trim();
  const region = h("section", { class: "result", "aria-live": "off", "aria-label": "AIBOM result" });
  const { form } = modelForm(model);
  clear(root).append(header(), form, region);

  if (model) {
    load(model, region, signal);
  } else {
    region.append(idleState());
  }
}
