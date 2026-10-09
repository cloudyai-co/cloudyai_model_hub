/**
 * Hash router. Routes live in the URL fragment, so the static host needs no rewrite rules and every
 * view can be bookmarked or shared (for example #/aibom?model=Qwen/Qwen2.5-7B-Instruct).
 */

export const ROUTE_NAMES = Object.freeze(["overview", "aibom", "selection"]);

/** Parse a location hash into { name, params }. Unknown paths fall back to the overview. */
export function parseHash(hash = window.location.hash) {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const [pathPart = "", queryPart = ""] = raw.split("?", 2);
  const key = pathPart.replace(/^\/+|\/+$/g, "") || "overview";
  const name = ROUTE_NAMES.includes(key) ? key : "overview";
  return { name, params: new URLSearchParams(queryPart) };
}

/** Build a hash for a route. Empty parameter values are left out. */
export function routeHref(name, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const path = name === "overview" ? "/" : `/${name}`;
  const search = query.toString();
  return `#${path}${search ? `?${search}` : ""}`;
}

const listeners = new Set();

/** Subscribe to route changes. Returns an unsubscribe function. */
export function onRouteChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit() {
  const route = parseHash();
  for (const listener of listeners) listener(route);
}

/** Start listening. Normalises an empty hash to the overview. */
export function startRouter() {
  window.addEventListener("hashchange", emit);
  if (!window.location.hash) history.replaceState(null, "", "#/");
  emit();
}

/** Navigate to a route. Navigating to the current URL re-renders the view. */
export function navigate(name, params = {}) {
  const target = routeHref(name, params);
  if (window.location.hash === target) emit();
  else window.location.hash = target;
}
