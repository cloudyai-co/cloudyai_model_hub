async function initSelection() {
  const searchForm = document.getElementById("selection-search-form");
  const searchInput = document.getElementById("selection-search-input");
  const resultsEl = document.getElementById("selection-results");
  const reqForm = document.getElementById("requirements-form");
  const reqModelInput = document.getElementById("requirements-model-input");

  await populateDtypeOptions();

  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = searchInput.value.trim();
    if (!q) return;
    resultsEl.innerHTML = `<p class="status status-loading">Searching Hugging Face…</p>`;
    try {
      const models = await Api.searchModels(q);
      renderSearchResults(models, resultsEl, reqModelInput);
    } catch (err) {
      resultsEl.innerHTML = `<p class="status status-error">Search failed: ${err.message}</p>`;
    }
  });

  reqForm.addEventListener("submit", (e) => {
    e.preventDefault();
    runRequirements();
  });
}

async function populateDtypeOptions() {
  const select = document.getElementById("dtype-select");
  try {
    const dtypes = await Api.dtypes();
    select.innerHTML = dtypes.map((d) => `<option value="${d.id}">${d.label}</option>`).join("");
    select.value = "fp16";
  } catch (_) {
    select.innerHTML = `<option value="fp16">FP16 / BF16 (half precision)</option>`;
  }
}

function renderSearchResults(models, resultsEl, reqModelInput) {
  if (!models.length) {
    resultsEl.innerHTML = `<p class="status">No models matched that search — try a shorter or more general term.</p>`;
    return;
  }
  resultsEl.innerHTML = "";
  models.forEach((m) => resultsEl.appendChild(buildModelCard(m, { onAnalyze: reqModelInput })));
}

function buildModelCard(m, { onAnalyze } = {}) {
  const card = document.createElement("div");
  card.className = "model-card";
  card.innerHTML = `
    <div class="model-card-main">
      <span class="model-id">${m.id}</span>
      <span class="model-meta">${m.pipeline_tag || "—"} · ${formatNumber(m.downloads)} downloads · ${formatNumber(m.likes || 0)} likes${m.gated ? ' <span class="badge badge-warning">gated</span>' : ""}</span>
    </div>
    <div class="model-card-actions">
      <button class="btn-icon copy-btn" type="button" title="Copy model id">⧉</button>
      ${onAnalyze ? '<button class="btn-secondary analyze-btn" type="button">Analyze</button>' : ""}
    </div>`;
  card.querySelector(".copy-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(m.id);
  });
  if (onAnalyze) {
    card.querySelector(".analyze-btn").addEventListener("click", () => {
      onAnalyze.value = m.id;
      runRequirements();
      document.getElementById("requirements-panel").scrollIntoView({ behavior: "smooth" });
    });
  }
  return card;
}

async function runRequirements() {
  const model = document.getElementById("requirements-model-input").value.trim();
  if (!model) return;
  const dtype = document.getElementById("dtype-select").value;
  const contextLength = document.getElementById("context-length-input").value || 4096;
  const batchSize = document.getElementById("batch-size-input").value || 1;

  const panel = document.getElementById("requirements-panel");
  const body = document.getElementById("requirements-body");
  const status = document.getElementById("requirements-status");
  panel.classList.remove("hidden");
  body.classList.add("hidden");
  status.textContent = "Fetching model metadata and calculating…";
  status.className = "status status-loading";

  try {
    const data = await Api.getRequirements(model, dtype, contextLength, batchSize);
    renderRequirements(data);
    status.textContent = "";
    status.className = "status";
    body.classList.remove("hidden");
  } catch (err) {
    status.textContent = `Couldn't calculate requirements: ${err.message}`;
    status.className = "status status-error";
  }
}

function renderRequirements(data) {
  document.getElementById("requirements-model-title").textContent = data.model_id;

  const paramsB = (data.param_count / 1e9).toFixed(2);
  document.getElementById("requirements-param-count").textContent =
    `${paramsB}B parameters` +
    (data.param_count_is_estimate
      ? " — estimated from config.json (no safetensors metadata found on this repo)"
      : " — from safetensors metadata");

  renderMemoryBar(data.estimate);
  renderHardwareTable(data.recommendations);
  renderComplexity(data.complexity);
  renderAlternatives(data.alternatives || []);
}

function renderMemoryBar(estimate) {
  const bar = document.getElementById("memory-bar");
  const legend = document.getElementById("memory-legend");
  const segments = [
    { label: "Weights", value: estimate.weights_gb, cls: "seg-weights" },
    { label: "KV cache", value: estimate.kv_cache_gb, cls: "seg-kv" },
    { label: "Activations", value: estimate.activation_overhead_gb, cls: "seg-activations" },
    { label: "Framework overhead", value: estimate.framework_overhead_gb, cls: "seg-overhead" },
  ];
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;

  bar.innerHTML = segments
    .map((s) => `<div class="${s.cls}" style="width:${(s.value / total) * 100}%" title="${s.label}: ${s.value} GB"></div>`)
    .join("");

  legend.innerHTML =
    segments
      .map((s) => `<span class="legend-item"><span class="legend-swatch ${s.cls}"></span>${s.label}: <strong>${s.value} GB</strong></span>`)
      .join("") + `<span class="legend-total">Total: ${estimate.total_gb} GB</span>`;
}

function renderHardwareTable(recs) {
  const tbody = document.getElementById("requirements-hardware-table");
  tbody.innerHTML = recs
    .map(
      (r) => `<tr class="${r.fits_single_gpu ? "row-good" : ""}">
        <td>${r.name}</td>
        <td class="mono">${r.vram_gb} GB</td>
        <td class="mono">${r.gpus_needed}</td>
        <td>${r.interconnect_required}</td>
        <td class="mono">${r.approx_tokens_per_sec_single_stream ?? "—"}</td>
      </tr>`
    )
    .join("");
}

function renderComplexity(complexity) {
  const el = document.getElementById("requirements-complexity");
  if (!complexity) {
    el.innerHTML = "";
    return;
  }
  const levelClass =
    { Low: "badge-good", Medium: "badge-warning", High: "badge-bad", "Very High": "badge-bad" }[complexity.level] || "";
  el.innerHTML = `
    <span class="badge ${levelClass}">${complexity.level}</span>
    <ul class="reason-list">${complexity.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>
  `;
}

function renderAlternatives(alts) {
  const wrap = document.getElementById("requirements-alternatives-wrap");
  const el = document.getElementById("requirements-alternatives");
  if (!alts.length) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  el.innerHTML = "";
  alts.forEach((m) => el.appendChild(buildModelCard(m)));
}
