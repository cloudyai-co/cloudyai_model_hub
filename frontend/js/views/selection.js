/** Model selection: search Hugging Face, then estimate memory, hardware fit and operational complexity. */

import { ApiError, getJson } from "../api.js";
import { clear, h, icon } from "../dom.js";
import {
  alertBox,
  button,
  chips,
  dataTable,
  emptyNote,
  factList,
  field,
  linkButton,
  sectionHead,
  statusLine,
  subTitle,
} from "../components/ui.js";
import { EMPTY, formatCompact, formatGigabytes, formatInt, formatParameters, formatVram } from "../format.js";
import { navigate, routeHref } from "../router.js";

const CONTEXT_PRESETS = ["2048", "4096", "8192", "32768", "131072"];

/** Defaults match the API defaults, so an empty URL gives the same estimate as an explicit one. */
const DEFAULTS = Object.freeze({ dtype: "fp16", context: "4096", batch: "1" });

let dtypeCache = null;

async function loadDtypes(signal) {
  if (!dtypeCache) dtypeCache = await getJson("dtypes", undefined, { signal });
  return dtypeCache;
}

function errorText(error) {
  return error instanceof ApiError ? error.message : "Something unexpected went wrong. Try again in a moment.";
}

function hero() {
  return h(
    "header",
    { class: "page-head" },
    h("p", { class: "eyebrow" }, h("span", { class: "dot", "aria-hidden": "true" }), "02 · Model selection"),
    h("h1", { class: "display" }, "Fit the model to the hardware."),
    h(
      "p",
      { class: "lede" },
      "Search Hugging Face, then estimate what a model needs: weight and KV-cache memory by precision " +
        "and context length, the accelerators that fit, and how hard the model is to operate.",
    ),
  );
}

/** Links that keep the current search and analysis options. */
function rowActions(id, options) {
  return h(
    "div",
    { class: "row-actions" },
    linkButton("Estimate", routeHref("selection", { ...options, model: id }), { small: true }),
    linkButton("AIBOM", routeHref("aibom", { model: id }), { small: true }),
  );
}

function resultsTable(results, options) {
  return dataTable({
    caption: `${formatInt(results.length)} ${results.length === 1 ? "result" : "results"}, most downloaded first`,
    columns: [
      { label: "Model", wrap: true },
      { label: "Downloads", numeric: true },
      { label: "Likes", numeric: true },
      { label: "Task" },
      { label: "Library" },
      { label: "Actions", align: "end" },
    ],
    rows: results.map((item) => ({
      cells: [
        h("a", { href: routeHref("selection", { ...options, model: item.id }), class: "cell-id" }, item.id),
        formatCompact(item.downloads),
        formatCompact(item.likes),
        item.pipeline_tag || EMPTY,
        item.library_name || EMPTY,
        rowActions(item.id, options),
      ],
    })),
  });
}

async function runSearch(query, region, options, signal) {
  region.replaceChildren(statusLine(`Searching for “${query}”`, { busy: true }));
  try {
    const body = await getJson("models/search", { q: query, limit: 12 }, { signal });
    if (signal.aborted) return;
    const results = Array.isArray(body.results) ? body.results : [];
    region.replaceChildren(
      results.length ? resultsTable(results, options) : emptyNote(`No models match “${query}”. Try a shorter name.`),
    );
  } catch (error) {
    if (signal.aborted) return;
    region.replaceChildren(alertBox("Search failed", errorText(error)));
  }
}

function searchSection(options, signal) {
  const query = options.q;
  const input = h("input", {
    id: "query-input",
    name: "q",
    type: "search",
    class: "input input-lg",
    value: query,
    placeholder: "Name or keyword, for example qwen instruct",
    autocomplete: "off",
    minlength: 2,
    maxlength: 100,
  });
  const submit = button("Search", { variant: "primary", iconName: "search" });
  submit.type = "submit";
  const form = h(
    "form",
    {
      class: "form",
      role: "search",
      onsubmit: (event) => {
        event.preventDefault();
        navigate("selection", { ...options, q: input.value.trim() });
      },
    },
    h(
      "div",
      { class: "form-row" },
      field({ id: "query-input", label: "Search Hugging Face models", control: input, className: "search-field" }),
      submit,
    ),
  );

  const results = h("div", { class: "results" });
  if (query) runSearch(query, results, options, signal);
  else results.append(emptyNote("Search by model name. Results are sorted by downloads."));

  return h(
    "section",
    { class: "section", "aria-labelledby": "sec-search" },
    sectionHead("01", "Find a model", "Results link to an estimate and to the AIBOM generator."),
    form,
    results,
  );
}

/** Stacked bar and legend for the memory breakdown. Widths are set through CSSOM, not style attributes. */
function memoryBreakdown(estimate) {
  const parts = [
    { label: "Weights", value: estimate.weights_gb, className: "seg-weights" },
    { label: "KV cache", value: estimate.kv_cache_gb, className: "seg-kv" },
    { label: "Activations", value: estimate.activation_overhead_gb, className: "seg-act" },
    { label: "Framework", value: estimate.framework_overhead_gb, className: "seg-fw" },
  ];
  const values = parts.map((part) => Math.max(0, Number(part.value) || 0));
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const bar = h(
    "div",
    { class: "stack-bar", "aria-hidden": "true" },
    parts.map((part, index) => {
      const segment = h("span", { class: part.className });
      segment.style.width = `${(100 * values[index]) / total}%`;
      return segment;
    }),
  );
  const legend = h(
    "ul",
    { class: "legend" },
    parts.map((part, index) =>
      h(
        "li",
        {},
        h("span", { class: `swatch ${part.className}`, "aria-hidden": "true" }),
        h("span", {}, part.label),
        h("span", { class: "value" }, formatGigabytes(values[index])),
      ),
    ),
  );
  return h("div", {}, bar, legend);
}

function hardwareTable(hardware) {
  return dataTable({
    caption: "Accelerators, rounded spec-sheet figures",
    columns: [
      { label: "Accelerator" },
      { label: "Memory", numeric: true },
      { label: "GPUs", numeric: true },
      { label: "Fits one device" },
      { label: "Interconnect", wrap: true },
      { label: "Tokens/s, one stream", numeric: true },
    ],
    rows: hardware.map((item) => ({
      cells: [
        item.name,
        formatVram(Number(item.vram_gb)),
        formatInt(item.gpus_needed),
        item.fits_single_gpu
          ? h("span", { class: "fit fit-yes" }, icon("check", "Yes"), "Yes")
          : h("span", { class: "fit fit-no" }, icon("x", "No"), "No"),
        item.interconnect_required || EMPTY,
        formatInt(item.approx_tokens_per_sec_single_stream),
      ],
    })),
  });
}

function complexityBlock(complexity) {
  return h(
    "div",
    { class: "complexity" },
    h("p", { class: "eyebrow" }, "Operational complexity"),
    h("p", { class: "level" }, complexity.level || EMPTY),
    h("ul", { class: "reasons" }, (complexity.reasons || []).map((reason) => h("li", {}, reason))),
  );
}

function alternativesBlock(alternatives, options) {
  if (!alternatives.length) return null;
  return h(
    "div",
    {},
    subTitle("Related models, same architecture family"),
    h(
      "ul",
      { class: "link-list" },
      alternatives.map((item) =>
        h(
          "li",
          {},
          h("a", { class: "cell-id", href: routeHref("selection", { ...options, model: item.id }) }, item.id),
          h("span", { class: "muted small" }, `${formatCompact(item.downloads)} downloads`),
          rowActions(item.id, options),
        ),
      ),
    ),
  );
}

function capacityReport(data, options) {
  const { estimate } = data;
  const sourceNote = data.parameter_source === "safetensors" ? "From safetensors metadata" : "Estimated from config.json";
  return h(
    "div",
    { class: "capacity" },
    factList([
      { label: "Parameters", value: formatParameters(data.parameters), note: sourceNote },
      { label: "Precision", value: data.dtype_label || data.dtype },
      { label: "Context", value: `${formatInt(estimate.context_length)} tokens` },
      { label: "Batch", value: `${formatInt(estimate.batch_size)} ${estimate.batch_size === 1 ? "sequence" : "sequences"}` },
    ]),
    h(
      "div",
      { class: "capacity-split" },
      h(
        "div",
        { class: "memory" },
        h("p", { class: "eyebrow" }, "Estimated memory per instance"),
        h("p", { class: "memory-total" }, h("span", { class: "big" }, formatGigabytes(estimate.total_gb))),
        memoryBreakdown(estimate),
        data.kv_cache_estimated
          ? null
          : h("p", { class: "small muted" }, "The config has no layer data, so the KV cache is not included."),
      ),
      complexityBlock(data.complexity || {}),
    ),
    hardwareTable(data.hardware || []),
    alternativesBlock(data.alternatives || [], options),
    h(
      "p",
      { class: "legal-note" },
      "Estimates from public metadata, a standard transformer memory model and rounded spec-sheet figures. " +
        "Measure on the hardware you plan to use before you buy or commit.",
    ),
  );
}

async function runCapacity(model, options, region, signal) {
  region.replaceChildren(statusLine(`Estimating memory and hardware for ${model}`, { busy: true }));
  try {
    const data = await getJson(
      "requirements",
      { model, dtype: options.dtype, context_length: options.context, batch_size: options.batch },
      { signal },
    );
    if (signal.aborted) return;
    region.replaceChildren(capacityReport(data, options));
  } catch (error) {
    if (signal.aborted) return;
    region.replaceChildren(alertBox("No estimate", errorText(error)));
  }
}

function capacitySection(options, signal) {
  const model = options.model;
  const modelInput = h("input", {
    id: "capacity-model",
    name: "model",
    type: "text",
    class: "input input-mono",
    value: model,
    placeholder: "org/model-name",
    autocomplete: "off",
    maxlength: 200,
  });
  const dtypeSelect = h("select", { id: "dtype-select", name: "dtype", class: "select" }, h("option", { value: options.dtype }, options.dtype));
  const contextInput = h("input", {
    id: "context-input",
    name: "context",
    type: "number",
    class: "input",
    min: 128,
    max: 262144,
    step: 1,
    value: options.context,
    inputmode: "numeric",
  });
  const batchInput = h("input", {
    id: "batch-input",
    name: "batch",
    type: "number",
    class: "input",
    min: 1,
    max: 256,
    step: 1,
    value: options.batch,
    inputmode: "numeric",
  });

  loadDtypes(signal)
    .then((list) => {
      dtypeSelect.replaceChildren(...list.map((item) => h("option", { value: item.id }, item.label)));
      dtypeSelect.value = options.dtype;
    })
    .catch(() => {
      // Keep the single default option. The server still applies the same default.
    });

  const submit = button("Estimate", { variant: "primary", iconName: "arrow" });
  submit.type = "submit";
  const form = h(
    "form",
    {
      class: "form",
      onsubmit: (event) => {
        event.preventDefault();
        const next = modelInput.value.trim();
        if (!next) {
          modelInput.focus();
          return;
        }
        navigate("selection", {
          q: options.q,
          model: next,
          dtype: dtypeSelect.value,
          context: contextInput.value.trim(),
          batch: batchInput.value.trim(),
        });
      },
    },
    h(
      "div",
      { class: "form-row" },
      field({ id: "capacity-model", label: "Model id or link", control: modelInput, className: "model-field" }),
      submit,
    ),
    h(
      "div",
      { class: "form-row options-row" },
      field({
        id: "dtype-select",
        label: "Precision",
        control: h("div", { class: "select-wrap" }, dtypeSelect, icon("chevron-down")),
      }),
      field({ id: "context-input", label: "Context tokens", control: contextInput }),
      field({ id: "batch-input", label: "Batch", control: batchInput }),
    ),
    chips("Context", CONTEXT_PRESETS, (value) => {
      contextInput.value = value;
    }),
  );

  const region = h("div", { class: "capacity-region" });
  if (model) runCapacity(model, options, region, signal);
  else region.append(emptyNote("Pick a model from the search results, or enter a model id above."));

  return h(
    "section",
    { class: "section", "aria-labelledby": "sec-capacity" },
    sectionHead("02", "Estimate capacity", "Memory is weights plus KV cache, with activation and framework overhead."),
    form,
    region,
  );
}

/** Route handler for #/selection?q=...&model=...&dtype=...&context=...&batch=... */
export function renderSelection(root, params, { signal }) {
  const options = {
    q: (params.get("q") || "").trim(),
    model: (params.get("model") || "").trim(),
    dtype: params.get("dtype") || DEFAULTS.dtype,
    context: params.get("context") || DEFAULTS.context,
    batch: params.get("batch") || DEFAULTS.batch,
  };
  clear(root).append(hero(), searchSection(options, signal), capacitySection(options, signal));
}
