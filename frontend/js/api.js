/**
 * Client for the CloudyAI API (same origin, under /api). Errors become ApiError with a message that
 * is safe to show to people. Requests can be cancelled through an AbortSignal, and time out after
 * TIMEOUT_MS.
 */

export const TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const STATUS_MESSAGES = {
  400: "That input is not a valid Hugging Face model id.",
  403: "This model is gated or private. Accept its terms on Hugging Face first.",
  404: "No model with that id was found on Hugging Face.",
  422: "Some of the options are not valid.",
  429: "Hugging Face is rate limiting requests. Wait a minute and try again.",
  502: "Hugging Face did not respond. Try again shortly.",
};

/** Absolute URL for an API path, relative to the page so the app also works below a sub-path. */
export function apiUrl(path, params = {}) {
  const url = new URL(`api/${path}`, document.baseURI);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url;
}

/** Turn a FastAPI `detail` value (string or validation list) into one readable sentence. */
export function describeDetail(detail, status) {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? String(item.loc[item.loc.length - 1]) : "";
        const message = typeof item?.msg === "string" ? item.msg : "";
        return message ? (field && field !== "body" ? `${field}: ${message}` : message) : "";
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return STATUS_MESSAGES[status] ?? `The request failed (HTTP ${status || "error"}).`;
}

async function errorFromResponse(response) {
  let detail = null;
  try {
    const body = await response.json();
    detail = body?.detail ?? null;
  } catch {
    // Not JSON (for example a proxy page). Fall back to the status message.
  }
  return new ApiError(describeDetail(detail, response.status), response.status);
}

/**
 * fetch() with a timeout that can also be cancelled by the caller. The returned `release` must be
 * called once the body has been read.
 */
function guardedFetch(url, { signal, accept }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("Timed out", "TimeoutError")), TIMEOUT_MS);
  const forward = () => controller.abort(signal.reason);
  if (signal) {
    if (signal.aborted) controller.abort(signal.reason);
    else signal.addEventListener("abort", forward, { once: true });
  }
  const release = () => {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forward);
  };
  const promise = fetch(url, {
    headers: { Accept: accept },
    credentials: "same-origin",
    signal: controller.signal,
  });
  return { promise, release, timedOut: () => controller.signal.reason?.name === "TimeoutError" };
}

async function request(path, params, { signal, accept = "application/json" } = {}) {
  const guard = guardedFetch(apiUrl(path, params), { signal, accept });
  try {
    return await guard.promise;
  } catch (error) {
    if (signal?.aborted) throw error;
    const message = guard.timedOut()
      ? "The request timed out. Try again in a moment."
      : "Could not reach the server. Check your connection and try again.";
    throw new ApiError(message, 0);
  } finally {
    guard.release();
  }
}

/** GET a JSON endpoint and return the parsed body. */
export async function getJson(path, params, options) {
  const response = await request(path, params, options);
  if (!response.ok) throw await errorFromResponse(response);
  return response.json();
}

/** GET a binary endpoint and save it as a file. The server's Content-Disposition name is used when present. */
export async function downloadFile(path, params, { signal, fallbackName, accept } = {}) {
  const response = await request(path, params, {
    signal,
    accept: accept ?? "application/octet-stream",
  });
  if (!response.ok) throw await errorFromResponse(response);
  const blob = await response.blob();
  const name = filenameFromHeader(response.headers.get("Content-Disposition")) || fallbackName || "download";
  saveBlob(blob, name);
  return name;
}

/** The `filename="..."` value of a Content-Disposition header, restricted to safe characters. */
export function filenameFromHeader(value) {
  if (!value) return null;
  const match = /filename="([^"]+)"/i.exec(value);
  if (!match) return null;
  const name = match[1].replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[-.]+/, "").slice(0, 160);
  return name || null;
}

/** Save a Blob through a temporary object URL and a download link. */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
