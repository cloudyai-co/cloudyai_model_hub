/**
 * Shared interface pieces. Every function returns DOM nodes built with `h()`, so no HTML strings are parsed.
 */

import { copyText, h, icon } from "../dom.js";
import { EMPTY, levelLabel } from "../format.js";
import { routeHref } from "../router.js";

/** Numbered section heading, for example "01  Identity". */
export function sectionHead(number, title, note) {
  return h(
    "div",
    { class: "section-head" },
    h("span", { class: "section-num", "aria-hidden": "true" }, number),
    h("h3", { class: "section-title" }, title),
    note ? h("p", { class: "section-note" }, note) : null,
  );
}

/** Label + control + hint, with the label bound to the control. */
export function field({ id, label, hint, control, className = "" }) {
  return h(
    "div",
    { class: `field ${className}`.trim() },
    h("label", { class: "field-label", htmlFor: id }, label),
    control,
    hint ? h("p", { class: "field-hint", id: `${id}-hint` }, hint) : null,
  );
}

/** A button. `variant` is "primary", "quiet" or "" (outline, the default). */
export function button(label, { variant = "", iconName = null, onClick, type = "button", small = false, disabled = false } = {}) {
  const classes = ["btn", variant ? `btn-${variant}` : "", small ? "btn-sm" : ""].filter(Boolean).join(" ");
  return h(
    "button",
    { type, class: classes, onclick: onClick, disabled },
    iconName ? icon(iconName) : null,
    h("span", {}, label),
  );
}

/** An in-app link styled as a button. */
export function linkButton(label, href, { variant = "", iconName = null, small = false } = {}) {
  const classes = ["btn", variant ? `btn-${variant}` : "", small ? "btn-sm" : ""].filter(Boolean).join(" ");
  return h("a", { class: classes, href }, h("span", {}, label), iconName ? icon(iconName) : null);
}

/** Link text styled as an underlined action. */
export function textLink(label, href, iconName = "arrow") {
  return h("a", { class: "text-button", href }, label, icon(iconName));
}

/** A link to an external page, opened in a new tab. Only https URLs are accepted. */
export function externalLink(href, text) {
  const safe = safeHttpsUrl(href);
  if (!safe) return h("span", {}, text);
  return h(
    "a",
    { href: safe, target: "_blank", rel: "noopener noreferrer" },
    text,
    h("span", { class: "sr-only" }, " (opens in a new tab)"),
    icon("external"),
  );
}

/** Return the URL if it is an absolute https URL, otherwise null. */
export function safeHttpsUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/** Copy-to-clipboard button. It briefly says "Copied" or "Copy failed". */
export function copyButton(text, label = "Copy", { small = true } = {}) {
  const node = button(label, { iconName: "copy", small, variant: "quiet" });
  const labelNode = node.querySelector("span");
  node.addEventListener("click", async () => {
    const ok = await copyText(text);
    labelNode.textContent = ok ? "Copied" : "Copy failed";
    setTimeout(() => {
      labelNode.textContent = label;
    }, 1800);
  });
  return node;
}

/** Live status line with an optional moving bar. */
export function statusLine(message, { busy = false } = {}) {
  return h(
    "div",
    { class: "status-block" },
    h("p", { class: "status", role: "status" }, message),
    busy ? h("div", { class: "busy", "aria-hidden": "true" }) : null,
  );
}

/** Error panel. Uses role=alert so screen readers announce it. */
export function alertBox(title, message) {
  return h(
    "div",
    { class: "alert", role: "alert" },
    h("p", { class: "alert-title" }, title),
    h("p", {}, message),
  );
}

/** Empty-state paragraph. */
export function emptyNote(message) {
  return h("p", { class: "empty" }, message);
}

/** Definition list of facts. Each item: { label, value, note, mono }. */
export function factList(items) {
  return h(
    "dl",
    { class: "facts" },
    items.map((item) =>
      h(
        "div",
        {},
        h("dt", {}, item.label),
        h(
          "dd",
          { class: item.mono ? "mono" : "" },
          item.value ?? EMPTY,
          item.note ? h("span", { class: "note" }, item.note) : null,
        ),
      ),
    ),
  );
}

/** Table with a caption and optional numeric columns. Cells can be strings or nodes. */
/** Class for a column's header or body cell: numbers are right-aligned, `align: "end"` holds actions. */
function columnClass(column, { header = false } = {}) {
  if (!column) return "";
  if (column.numeric) return "num";
  if (column.align === "end") return "col-end";
  return !header && column.wrap ? "wrap-anywhere" : "";
}

export function dataTable({ caption, columns, rows, id }) {
  const head = h(
    "tr",
    {},
    columns.map((column) => h("th", { scope: "col", class: columnClass(column, { header: true }) }, column.label)),
  );
  const body = h(
    "tbody",
    {},
    rows.map((row) =>
      h(
        "tr",
        { hidden: row.hidden ?? false },
        row.cells.map((cell, index) => h("td", { class: columnClass(columns[index]) }, cell)),
      ),
    ),
  );
  return h(
    "div",
    { class: "table-wrap" },
    h("table", { id: id ?? null }, caption ? h("caption", {}, caption) : null, h("thead", {}, head), body),
  );
}

/** Level badge: strong, partial or sparse, as text with a border (never colour alone). */
export function levelBadge(level) {
  return h("span", { class: `badge badge-${level}` }, levelLabel(level));
}

/** Completeness checklist. Present items show a tick, missing items a dash, and both are labelled in text. */
export function checklist(breakdown) {
  return h(
    "ul",
    { class: "checklist" },
    breakdown.map((item) =>
      h(
        "li",
        { class: item.present ? "is-present" : "is-missing" },
        icon(item.present ? "check" : "minus"),
        h(
          "span",
          {},
          h("span", { class: "sr-only" }, item.present ? "Present: " : "Missing: "),
          item.label,
        ),
        h("span", { class: "weight" }, `${item.weight}`),
      ),
    ),
  );
}

/** Row of example chips. Each chip calls onPick with its value. */
export function chips(label, values, onPick) {
  return h(
    "div",
    { class: "chips" },
    h("span", { class: "chips-label" }, label),
    values.map((value) => h("button", { type: "button", class: "chip", onclick: () => onPick(value) }, value)),
  );
}

/** Link to a route with the given parameters. */
export function routeLink(name, params, label) {
  return h("a", { href: routeHref(name, params) }, label);
}

/** Heading for a card-like aside or sub-block. */
export function subTitle(text) {
  return h("h4", { class: "sub-title" }, text);
}

/**
 * A margin note in the author's voice: serif italic, like pencil in the edge of a printed sheet.
 * Children may be strings or nodes, so callers can underline a phrase with the .squig class.
 */
export function handNote(children, { small = false } = {}) {
  return h("p", { class: small ? "hand hand-sm" : "hand" }, ...(Array.isArray(children) ? children : [children]));
}

/** A rubber-stamp annotation: uppercase mono inside a doubled rule, set a touch off square. */
export function inkStamp(text) {
  return h("p", { class: "stamp" }, text);
}
