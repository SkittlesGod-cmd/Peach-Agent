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

// Terminal copy buttons
document.querySelectorAll('.term').forEach(term => {
  const bar  = term.querySelector('.term-bar');
  const body = term.querySelector('.term-body');
  if (!bar || !body) return;

  // Wrap existing dots in .term-dots so flex space-between works
  const dots = Array.from(bar.querySelectorAll('.term-dot'));
  if (dots.length) {
    const wrap = document.createElement('span');
    wrap.className = 'term-dots';
    bar.insertBefore(wrap, dots[0]);
    dots.forEach(d => wrap.appendChild(d));
  }

  const btn = document.createElement('button');
  btn.className = 'term-copy';
  btn.textContent = 'Copy';
  bar.appendChild(btn);

  btn.addEventListener('click', () => {
    const text = body.textContent.trim();
    const done = () => {
      btn.textContent = 'Copied';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = 'Copy';
        btn.classList.remove('copied');
      }, 2000);
    };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(done).catch(done);
    } else {
      const ta = Object.assign(document.createElement('textarea'), {
        value: text, style: 'position:fixed;opacity:0'
      });
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      done();
    }
  });
});
