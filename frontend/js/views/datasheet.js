/**
 * The AIBOM datasheet: a printable, sectioned view of one CycloneDX ML-BOM as returned by the API.
 * Everything from the model card is shown as text. Nothing is parsed as HTML.
 */

import { ApiError, downloadFile, saveBlob } from "../api.js";
import { completenessRuler } from "../components/ruler.js";
import {
  alertBox,
  button,
  checklist,
  copyButton,
  dataTable,
  externalLink,
  factList,
  handNote,
  inkStamp,
  levelBadge,
  sectionHead,
  statusLine,
  subTitle,
} from "../components/ui.js";
import { h, icon } from "../dom.js";
import {
  EMPTY,
  formatBytes,
  formatCompact,
  formatDate,
  formatInt,
  formatParameters,
  formatTimestamp,
  levelLabel,
  parseWeightDtypes,
  shortHash,
} from "../format.js";

/** Rows shown before the "show all" control, to keep long repositories readable. */
const FILE_PREVIEW = 40;
const PUBLIC_HUB = "https://huggingface.co";

/** First value for each property name. */
export function propertyMap(properties = []) {
  const map = new Map();
  for (const prop of properties) {
    if (prop && typeof prop.name === "string" && !map.has(prop.name)) map.set(prop.name, prop.value);
  }
  return map;
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A safe file-name stem for downloads, for example "Qwen-Qwen2.5-7B-Instruct". */
export function slugOf(modelId) {
  return String(modelId).replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "model";
}

/** Public Hub page for a model. Each path segment is encoded, so the URL cannot escape the host. */
export function publicUrl(modelId) {
  return `${PUBLIC_HUB}/${String(modelId).split("/").map(encodeURIComponent).join("/")}`;
}

const ACCESS_LABELS = {
  open: "Open",
  "gated-auto": "Gated, automatic approval",
  "gated-manual": "Gated, manual approval",
  gated: "Gated",
};

function messageOf(error) {
  return error instanceof ApiError ? error.message : "Something unexpected went wrong. Try again.";
}

function actions({ modelId, bom, slug }) {
  const status = h("div", { class: "status-slot", "aria-live": "polite" });
  const pdf = button("Download PDF report", { variant: "primary", iconName: "pdf" });
  const json = button("Download CycloneDX JSON", { iconName: "download" });
  const text = JSON.stringify(bom, null, 2);

  pdf.addEventListener("click", async () => {
    pdf.disabled = true;
    status.replaceChildren(statusLine("Rendering the PDF report on the server", { busy: true }));
    try {
      const name = await downloadFile(
        "aibom/report.pdf",
        { model: modelId },
        { fallbackName: `${slug}-aibom.pdf`, accept: "application/pdf" },
      );
      status.replaceChildren(statusLine(`Saved ${name}`));
    } catch (error) {
      status.replaceChildren(alertBox("PDF not available", messageOf(error)));
    } finally {
      pdf.disabled = false;
    }
  });

  json.addEventListener("click", () => {
    saveBlob(new Blob([text], { type: "application/vnd.cyclonedx+json" }), `${slug}.cdx.json`);
    status.replaceChildren(statusLine(`Saved ${slug}.cdx.json`));
  });

  return h(
    "div",
    { class: "ds-actions" },
    pdf,
    json,
    copyButton(text, "Copy JSON"),
    h(
      "a",
      { class: "btn btn-quiet btn-sm", href: publicUrl(modelId), target: "_blank", rel: "noopener noreferrer" },
      h("span", {}, "Hugging Face page"),
      icon("external"),
      h("span", { class: "sr-only" }, " (opens in a new tab)"),
    ),
    status,
  );
}

function identitySection(component, props, modelId) {
  const publisher = component.supplier?.name || component.group || EMPTY;
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-identity" },
    sectionHead("01", "Identity", "Who published the model, and which revision this document describes."),
    factList([
      { label: "Model", value: component.name || modelId },
      { label: "Publisher", value: publisher },
      { label: "Revision", value: props.get("hf:commitSha") || EMPTY, mono: true },
      { label: "Created", value: formatDate(props.get("hf:createdAt")) },
      { label: "Last modified", value: formatTimestamp(props.get("hf:lastModified")) },
      { label: "Library", value: props.get("hf:libraryName") || EMPTY },
      { label: "Access", value: ACCESS_LABELS[props.get("hf:accessMode")] || EMPTY },
      { label: "Downloads, 30 days", value: formatCompact(toNumber(props.get("hf:downloads"))) },
      { label: "Downloads, all time", value: formatCompact(toNumber(props.get("hf:downloadsAllTime"))) },
      { label: "Likes", value: formatInt(toNumber(props.get("hf:likes"))) },
    ]),
  );
}

function licenceSection(component) {
  const licences = (Array.isArray(component.licenses) ? component.licenses : []).map((entry) => entry?.license ?? {});
  const body = licences.length
    ? factList(
        licences.map((license, index) => ({
          label: licences.length > 1 ? `Licence ${index + 1}` : "Licence",
          value: license.id || license.name || EMPTY,
          mono: Boolean(license.id),
          note: license.id ? "SPDX identifier" : license.name ? "Custom licence" : null,
        })),
      )
    : h("p", { class: "muted" }, "No licence is declared in the model metadata.");
  const links = licences
    .filter((license) => license.url)
    .map((license) => h("li", {}, externalLink(license.url, "Licence text")));
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-licence" },
    sectionHead("02", "Licence", "Terms that apply to the weights. Check them before commercial use."),
    body,
    links.length ? h("ul", { class: "link-list" }, links) : null,
  );
}

function architectureSection(component, props) {
  const parameters = component.modelCard?.modelParameters ?? {};
  const count = toNumber(props.get("hf:totalParameters"));
  const datasets = Array.isArray(parameters.datasets) ? parameters.datasets : [];
  const weights = parseWeightDtypes(props.get("hf:weightDtypes"));
  const context = toNumber(props.get("hf:contextLength"));
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-architecture" },
    sectionHead("03", "Architecture", "Task, structure and size, as declared by the publisher."),
    factList([
      {
        label: "Task",
        value: parameters.task || EMPTY,
        note: parameters.task ? null : "No pipeline tag on the Hub",
      },
      { label: "Architecture family", value: parameters.architectureFamily || EMPTY, mono: true },
      { label: "Model class", value: parameters.modelArchitecture || EMPTY, mono: true },
      {
        label: "Parameters",
        value: count ? formatParameters(count) : "Not published",
        note: count ? "From safetensors metadata" : "Estimated from config.json on the Model selection page",
      },
      {
        label: "Weight dtypes",
        value: weights.length ? weights.map((item) => `${item.dtype}: ${formatParameters(item.count)}`).join(", ") : EMPTY,
      },
      { label: "Context length", value: context ? `${formatInt(context)} tokens` : EMPTY },
      { label: "Base model", value: props.get("hf:baseModel") || EMPTY, mono: true },
    ]),
    datasets.length
      ? h(
          "div",
          {},
          subTitle("Training datasets"),
          h(
            "ul",
            { class: "link-list" },
            datasets.map((dataset) =>
              h(
                "li",
                {},
                h("span", { class: "cell-id" }, dataset.name || EMPTY),
                dataset.contents?.url ? externalLink(dataset.contents.url, "Dataset page") : null,
              ),
            ),
          ),
        )
      : null,
  );
}

function evaluationSection(component) {
  const metrics = component.modelCard?.quantitativeAnalysis?.performanceMetrics ?? [];
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-evaluation" },
    sectionHead("04", "Evaluation", "Results as reported by the publisher. This tool does not verify them."),
    metrics.length
      ? dataTable({
          caption: `${formatInt(metrics.length)} reported results`,
          columns: [{ label: "Metric" }, { label: "Value", numeric: true }, { label: "Dataset", wrap: true }],
          rows: metrics.map((metric) => ({
            cells: [metric.type || EMPTY, metric.value ?? EMPTY, metric.slice || EMPTY],
          })),
        })
      : h("p", { class: "muted" }, "The model card reports no evaluation results (model-index)."),
  );
}

function considerationBlock(title, items) {
  return h(
    "div",
    { class: "consideration" },
    subTitle(title),
    items.length
      ? h(
          "ul",
          {},
          items.map((item) => h("li", {}, item)),
        )
      : h("p", { class: "empty-note" }, "Not documented in the model card."),
  );
}

function considerationsSection(component) {
  const considerations = component.modelCard?.considerations ?? {};
  const ethics = (considerations.ethicalConsiderations ?? []).map((item) => item?.name).filter(Boolean);
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-considerations" },
    sectionHead("05", "Considerations", "Use, limits and risks, quoted from the model card."),
    h(
      "div",
      { class: "considerations" },
      considerationBlock("Intended use", considerations.useCases ?? []),
      considerationBlock("Technical limitations", considerations.technicalLimitations ?? []),
      considerationBlock("Ethical considerations", ethics),
      considerationBlock("Intended users", considerations.users ?? []),
    ),
  );
}

function fileRows(files) {
  return files.map((file, index) => {
    const fileProps = propertyMap(file.properties);
    const digest = file.hashes?.find((hash) => hash.alg === "SHA-256")?.content;
    const digestCell = digest
      ? h("span", { class: "hash" }, shortHash(digest, 16), " ", copyButton(digest, "Copy"))
      : h("span", { class: "muted" }, "Not available");
    return {
      hidden: index >= FILE_PREVIEW,
      cells: [
        file.name,
        fileProps.get("aibom:fileRole") || EMPTY,
        formatBytes(toNumber(fileProps.get("hf:sizeBytes"))),
        fileProps.get("hf:storage") === "lfs" ? "LFS" : "Git",
        digestCell,
      ],
    };
  });
}

function filesSection(bom, props) {
  const files = Array.isArray(bom.components) ? bom.components : [];
  const reportedCount = toNumber(props.get("hf:fileCount"));
  const reportedBytes = toNumber(props.get("hf:totalSizeBytes"));
  const listedBytes = files.reduce((sum, file) => sum + (toNumber(propertyMap(file.properties).get("hf:sizeBytes")) ?? 0), 0);
  const hashed = files.filter((file) => Array.isArray(file.hashes) && file.hashes.length > 0).length;
  const truncated = reportedCount !== null && reportedCount > files.length;

  const table = files.length
    ? dataTable({
        caption: "Repository files",
        columns: [
          { label: "File", wrap: true },
          { label: "Role" },
          { label: "Size", numeric: true },
          { label: "Storage" },
          { label: "SHA-256" },
        ],
        rows: fileRows(files),
      })
    : h("p", { class: "muted" }, "The repository file list was not available for this model.");

  const footNote = truncated
    ? `The document lists the first ${formatInt(files.length)} of ${formatInt(reportedCount)} files.`
    : "Digests are the Hub's LFS object hashes.";
  const toggle = files.length > FILE_PREVIEW ? button(`Show all ${formatInt(files.length)} files`, { variant: "quiet", small: true }) : null;
  if (toggle) {
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      const rows = table.querySelector("tbody").rows;
      for (let index = FILE_PREVIEW; index < rows.length; index += 1) rows[index].hidden = expanded;
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.querySelector("span").textContent = expanded
        ? `Show all ${formatInt(files.length)} files`
        : `Show first ${formatInt(FILE_PREVIEW)} files`;
    });
    toggle.setAttribute("aria-expanded", "false");
  }

  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-files" },
    sectionHead("06", "Files", "Repository files and sizes. Large files carry their Git LFS SHA-256 digest."),
    h(
      "div",
      { class: "file-summary" },
      h("span", {}, `${formatInt(reportedCount ?? files.length)} files`),
      h("span", {}, formatBytes(reportedBytes ?? listedBytes)),
      h("span", {}, `${formatInt(hashed)} with SHA-256`),
    ),
    table,
    files.length
      ? h("div", { class: "table-foot" }, h("span", {}, footNote), toggle)
      : null,
  );
}

function documentSection(text) {
  return h(
    "section",
    { class: "ds-section", "aria-labelledby": "sec-document" },
    sectionHead("07", "Document", "The complete CycloneDX 1.6 JSON. The PDF attaches the same file as aibom.cdx.json."),
    h(
      "details",
      { class: "document" },
      h(
        "summary",
        {},
        icon("chevron"),
        h("span", {}, "CycloneDX 1.6 JSON"),
        h("span", { class: "muted small" }, formatBytes(new Blob([text]).size)),
      ),
      h("pre", {}, h("code", {}, text)),
    ),
  );
}

function scoreAside(completeness) {
  const { score, level, breakdown = [] } = completeness;
  return h(
    "aside",
    { class: "ds-aside", "aria-labelledby": "aside-title" },
    h("h3", { id: "aside-title", class: "aside-title" }, "Documentation completeness"),
    h(
      "div",
      { class: "score-figure" },
      h("span", { class: "score-value" }, String(score)),
      h("span", { class: "score-of" }, "of 100"),
      levelBadge(level),
    ),
    completenessRuler(score, level),
    h(
      "p",
      { class: "small muted" },
      `${levelLabel(level)} documentation coverage. The score measures what is written down, not model quality, safety or legal compliance.`,
    ),
    checklist(breakdown),
    handNote(["The missing lines are the point — they are what to ", h("span", { class: "squig" }, "ask the publisher"), " about."], { small: true }),
  );
}

/**
 * Build the datasheet for an API response: { model_id, aibom, completeness }.
 * @returns {HTMLElement}
 */
export function buildDatasheet({ model_id: modelId, aibom: bom, completeness }) {
  const component = bom.metadata?.component ?? {};
  const props = propertyMap(component.properties);
  const text = JSON.stringify(bom, null, 2);
  const slug = slugOf(modelId);
  const group = component.group || null;
  const name = component.name || modelId;

  return h(
    "article",
    { class: "datasheet", "aria-labelledby": "ds-title" },
    h(
      "header",
      { class: "ds-head" },
      h("p", { class: "eyebrow" }, "AIBOM · CycloneDX 1.6 · Machine-learning BOM"),
      h("h2", { id: "ds-title", class: "ds-title" }, name),
      h(
        "p",
        { class: "ds-id" },
        group ? h("span", {}, group, h("span", { class: "sep", "aria-hidden": "true" }, "/")) : null,
        h("span", {}, name),
        h("span", { class: "sep", "aria-hidden": "true" }, "·"),
        h("span", {}, `Generated ${formatTimestamp(bom.metadata?.timestamp)}`),
      ),
      inkStamp("Reads public data · nothing downloaded"),
      actions({ modelId, bom, slug }),
    ),
    h(
      "div",
      { class: "ds-grid" },
      h(
        "div",
        { class: "ds-main" },
        identitySection(component, props, modelId),
        licenceSection(component),
        architectureSection(component, props),
        evaluationSection(component),
        considerationsSection(component),
        filesSection(bom, props),
        documentSection(text),
      ),
      scoreAside(completeness),
    ),
    h(
      "p",
      { class: "legal-note" },
      "Generated from public Hugging Face metadata. Check it against the model's own repository before " +
        "using it for compliance. The field mapping is described in docs/aibom-mapping.md.",
    ),
  );
}
