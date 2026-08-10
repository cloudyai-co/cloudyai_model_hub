function showView(viewId) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  const target = document.getElementById(`view-${viewId}`);
  if (!target) return;
  target.classList.remove("hidden");
  document.querySelectorAll(".nav-link").forEach((el) => el.classList.remove("active"));
  const link = document.querySelector(`.nav-link[data-view="${viewId}"]`);
  if (link) link.classList.add("active");
  window.location.hash = viewId;
}

function initNav() {
  document.querySelectorAll(".nav-link").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      showView(el.dataset.view);
    });
  });
  const initial = window.location.hash.replace("#", "") || "dashboard";
  showView(document.getElementById(`view-${initial}`) ? initial : "dashboard");
}

document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initDashboard();
  initSelection();
  initAibom();
  checkApiHealth();
});
