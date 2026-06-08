const yearTargets = document.querySelectorAll("[data-year]");
for (const target of yearTargets) {
  target.textContent = new Date().getFullYear();
}
