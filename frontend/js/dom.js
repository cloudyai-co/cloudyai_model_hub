/**
 * DOM helpers. Nothing in this file parses HTML: text always goes through text nodes, so untrusted
 * strings (model cards, file names, API errors) cannot run as markup. Styles are set through CSSOM
 * (node.style.x), never through style attributes, to stay inside the Content-Security-Policy.
 */

export const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * Create an HTML element.
 *
 * Special props: `class`, `text` (textContent), `dataset` (object), and `on<event>` handlers.
 * Any other prop is set as a DOM property when the element has one, otherwise as an attribute.
 * Children may be nodes, strings, numbers, arrays of those, or falsy values (skipped).
 */
export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (key === "style") {
      throw new TypeError("Use node.style.<property> instead of a style attribute (Content-Security-Policy).");
    } else if (value === true) node.setAttribute(key, "");
    else if (key.includes("-") || !(key in node)) node.setAttribute(key, String(value));
    else node[key] = value;
  }
  return append(node, children);
}

/** Append children (see `h`). Strings become text nodes. Returns the parent for chaining. */
export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

/** Create an SVG element with attributes. Attribute values are strings; `false`/`null` are skipped. */
export function svg(tag, attributes = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) continue;
    node.setAttribute(key, String(value));
  }
  return append(node, children);
}

/** An inline icon from the sprite in index.html. Pass a label for meaningful icons. */
export function icon(name, label) {
  const node = svg("svg", { class: "icon", viewBox: "0 0 24 24", focusable: "false" });
  if (label) {
    node.setAttribute("role", "img");
    node.append(svg("title", {}, label));
  } else {
    node.setAttribute("aria-hidden", "true");
  }
  node.append(svg("use", { href: `#i-${name}` }));
  return node;
}

/** Remove all children of `node`. */
export function clear(node) {
  node.replaceChildren();
  return node;
}

/** Copy text to the clipboard. Resolves to true on success. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
