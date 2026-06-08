// Year stamp
document.querySelectorAll('[data-year]').forEach(el => {
  el.textContent = new Date().getFullYear();
});

// Nav: add .scrolled class when page is scrolled
const nav = document.querySelector('.nav');
if (nav) {
  const tick = () => nav.classList.toggle('scrolled', window.scrollY > 24);
  window.addEventListener('scroll', tick, { passive: true });
  tick();
}
