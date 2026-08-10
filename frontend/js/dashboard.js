function initDashboard() {
  document.querySelectorAll("[data-goto]").forEach((el) => {
    el.addEventListener("click", () => showView(el.dataset.goto));
  });
}

async function checkApiHealth() {
  const dot = document.querySelector(".sidebar-footer .status-dot");
  const label = document.getElementById("api-status-text");
  try {
    await Api.health();
    dot.classList.remove("status-bad");
    dot.classList.add("status-ok");
    label.textContent = "API connected";
  } catch (err) {
    dot.classList.remove("status-ok");
    dot.classList.add("status-bad");
    label.textContent = "API unreachable — is uvicorn running?";
  }
}
