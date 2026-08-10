function initAibom() {
  const form = document.getElementById("aibom-form");
  const input = document.getElementById("aibom-model-input");
  const status = document.getElementById("aibom-status");
  const results = document.getElementById("aibom-results");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const model = input.value.trim();
    if (!model) return;
    status.textContent = "Fetching model metadata and generating AIBOM…";
    status.className = "status status-loading";
    results.classList.add("hidden");
    try {
      const data = await Api.generateAibom(model);
      renderAibom(data);
      status.textContent = "";
      status.className = "status";
    } catch (err) {
      status.textContent = `Couldn't generate AIBOM: ${err.message}`;
      status.className = "status status-error";
    }
  });
}

function renderAibom({ aibom, completeness }) {
  const results = document.getElementById("aibom-results");
  results.classList.remove("hidden");

  document.getElementById("completeness-score").textContent = `${completeness.score}%`;
  document.getElementById("completeness-ring").style.setProperty("--score", completeness.score);

  const breakdownEl = document.getElementById("completeness-breakdown");
  breakdownEl.innerHTML = completeness.breakdown
    .map(
      (item) => `<div class="check-row ${item.present ? "check-yes" : "check-no"}">
        <span class="check-icon">${item.present ? "✓" : "○"}</span><span>${item.label}</span>
      </div>`
    )
    .join("");

  const jsonEl = document.getElementById("aibom-json");
  const pretty = JSON.stringify(aibom, null, 2);
  jsonEl.innerHTML = syntaxHighlightJSON(pretty);

  document.getElementById("aibom-copy-btn").onclick = () => {
    navigator.clipboard.writeText(pretty);
    flashButton("aibom-copy-btn", "Copied!");
  };
  document.getElementById("aibom-download-btn").onclick = () => {
    const blob = new Blob([pretty], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${aibom.metadata.component.name}-aibom.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
}
