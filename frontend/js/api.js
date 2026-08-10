const API_BASE = "/api";

async function apiGet(path, params = {}) {
  const url = new URL(API_BASE + path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* response wasn't JSON — fall back to statusText */
    }
    throw new Error(detail);
  }
  return res.json();
}

const Api = {
  health: () => apiGet("/health"),
  dtypes: () => apiGet("/dtypes"),
  searchModels: (q, limit = 20) => apiGet("/models/search", { q, limit }),
  generateAibom: (model) => apiGet("/aibom/generate", { model }),
  getRequirements: (model, dtype, context_length, batch_size) =>
    apiGet("/requirements", { model, dtype, context_length, batch_size }),
};

function formatNumber(n) {
  if (n === undefined || n === null) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function flashButton(id, text) {
  const btn = document.getElementById(id);
  if (!btn) return;
  const original = btn.textContent;
  btn.textContent = text;
  setTimeout(() => (btn.textContent = original), 1500);
}

function syntaxHighlightJSON(json) {
  const escaped = json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return escaped.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = "json-number";
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? "json-key" : "json-string";
      } else if (/true|false/.test(match)) {
        cls = "json-boolean";
      } else if (/null/.test(match)) {
        cls = "json-null";
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}
