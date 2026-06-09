// ── Year stamp ────────────────────────────────────────────────────────────────
document.querySelectorAll('[data-year]').forEach(el => {
  el.textContent = new Date().getFullYear();
});

// ── Nav scroll class ──────────────────────────────────────────────────────────
const nav = document.querySelector('.nav');
if (nav) {
  const tick = () => nav.classList.toggle('scrolled', window.scrollY > 24);
  window.addEventListener('scroll', tick, { passive: true });
  tick();
}

// ── Scroll reveal ─────────────────────────────────────────────────────────────
const revealObs = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('is-visible');
      revealObs.unobserve(e.target);
    }
  });
}, { threshold: 0.08, rootMargin: '0px 0px -48px 0px' });

document.querySelectorAll('[data-reveal]').forEach(el => {
  const delay = el.dataset.delay;
  if (delay) el.style.transitionDelay = delay + 'ms';
  revealObs.observe(el);
});

// Stagger children of [data-stagger] containers
document.querySelectorAll('[data-stagger]').forEach(parent => {
  Array.from(parent.children).forEach((child, i) => {
    child.classList.add('stagger-child');
    child.style.transitionDelay = (i * 75) + 'ms';
    revealObs.observe(child);
  });
});

// ── Brand mark trace animation ────────────────────────────────────────────────
const brandPath = document.querySelector('.brand-icon path');
if (brandPath && brandPath.getTotalLength) {
  const len = brandPath.getTotalLength();
  brandPath.style.strokeDasharray = len;
  brandPath.style.strokeDashoffset = len;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      brandPath.style.transition = 'stroke-dashoffset 0.9s cubic-bezier(.4,0,.2,1) .15s';
      brandPath.style.strokeDashoffset = '0';
    });
  });
}

// ── Terminal copy buttons ─────────────────────────────────────────────────────
document.querySelectorAll('.term').forEach(term => {
  const bar  = term.querySelector('.term-bar');
  const body = term.querySelector('.term-body');
  if (!bar || !body) return;

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
      setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
    };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(done).catch(done);
    } else {
      const ta = Object.assign(document.createElement('textarea'), { value: text, style: 'position:fixed;opacity:0' });
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
      done();
    }
  });
});

// ── Charts ────────────────────────────────────────────────────────────────────

function seededRand(seed) {
  let s = seed >>> 0;
  return () => {
    s = Math.imul(1664525, s) + 1013904223 >>> 0;
    return s / 0xffffffff;
  };
}

function renderPortfolioChart() {
  const container = document.getElementById('pc-portfolio');
  if (!container) return;

  const rand  = seededRand(7);
  const days  = 90;
  const vals  = [52000];
  for (let i = 1; i < days; i++) {
    const drift = (rand() - 0.465) * 0.026 + 0.0018;
    vals.push(Math.max(46000, vals[i - 1] * (1 + drift)));
  }

  const last   = vals[vals.length - 1];
  const pct    = ((last / vals[0] - 1) * 100).toFixed(1);
  const up     = last >= vals[0];
  const color  = up ? '#4ade80' : '#f87171';
  const accent = '#e0784c';

  const W = 560, H = 160;
  const minV = Math.min(...vals) - 1200;
  const maxV = Math.max(...vals) + 1200;
  const tx = i => ((i / (days - 1)) * W).toFixed(2);
  const ty = v  => (H - ((v - minV) / (maxV - minV)) * H).toFixed(2);

  const coords = vals.map((v, i) => `${tx(i)},${ty(v)}`);
  const linePath = `M ${coords.join(' L ')}`;
  const areaPath = `${linePath} L ${W},${H} L 0,${H} Z`;

  // Subtle horizontal grid
  const grids = [0.25, 0.5, 0.75].map(t =>
    `<line x1="0" y1="${(H * t).toFixed(0)}" x2="${W}" y2="${(H * t).toFixed(0)}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`
  ).join('');

  container.innerHTML = `
    <div class="chart-header">
      <div>
        <div class="chart-meta">Portfolio · 90 days</div>
        <div class="chart-value">$${Math.round(last).toLocaleString()}</div>
      </div>
      <div class="chart-badge ${up ? 'chart-badge--up' : 'chart-badge--dn'}">${up ? '▲' : '▼'} ${Math.abs(pct)}%</div>
    </div>
    <svg class="chart-svg" viewBox="0 0 ${W} ${H}" height="160" preserveAspectRatio="none">
      <defs>
        <linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${accent}" stop-opacity="0.22"/>
          <stop offset="100%" stop-color="${accent}" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="pc"><rect width="${W}" height="${H}"/></clipPath>
      </defs>
      ${grids}
      <path d="${areaPath}" fill="url(#pg)" clip-path="url(#pc)"/>
      <path d="${linePath}" fill="none" stroke="${accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="cline"/>
    </svg>
    <div class="chart-tickers">
      ${['SPY','AAPL','NVDA','MSFT','TSLA'].map(t => `<span class="chart-ticker">${t}</span>`).join('')}
    </div>`;

  // Animate line on enter
  const path = container.querySelector('.cline');
  if (path && path.getTotalLength) {
    const len = path.getTotalLength();
    path.style.strokeDasharray = len;
    path.style.strokeDashoffset = len;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        path.style.transition = 'stroke-dashoffset 2.4s cubic-bezier(.4,0,.2,1) .2s';
        path.style.strokeDashoffset = '0';
        obs.disconnect();
      }
    }, { threshold: 0.3 });
    obs.observe(container);
  }
}

function renderCandlestickChart() {
  // (unused — using heatmap instead)
}

function renderHeatmap() {
  const container = document.getElementById('pc-heat');
  if (!container) return;

  const tickers = ['SPY','AAPL','NVDA','MSFT','TSLA'];
  const corr = [
    [1.00, 0.78, 0.63, 0.84, 0.39],
    [0.78, 1.00, 0.72, 0.87, 0.44],
    [0.63, 0.72, 1.00, 0.68, 0.51],
    [0.84, 0.87, 0.68, 1.00, 0.42],
    [0.39, 0.44, 0.51, 0.42, 1.00],
  ];

  const colorFor = v => {
    // 0 → red(0°), 0.5 → yellow(55°), 1 → green(140°)
    const hue = v * 140;
    const sat = 58 + v * 12;
    const lit = 28 + v * 18;
    return `hsl(${hue.toFixed(0)},${sat.toFixed(0)}%,${lit.toFixed(0)}%)`;
  };

  const colLabels = `
    <div class="hm-col-labels" style="grid-template-columns:repeat(${tickers.length},1fr);">
      ${tickers.map(t => `<span>${t}</span>`).join('')}
    </div>`;

  const rows = tickers.map((rowT, r) => `
    <div class="hm-row">
      <span class="hm-row-label">${rowT}</span>
      ${tickers.map((_, c) => {
        const v = corr[r][c];
        return `<div class="hm-cell" style="background:${colorFor(v)}" title="${rowT}/${tickers[c]}: ${v.toFixed(2)}">${v.toFixed(2)}</div>`;
      }).join('')}
    </div>`).join('');

  container.innerHTML = `
    <div class="chart-meta" style="margin-bottom:16px;">30-day correlation</div>
    <div class="hm-wrap">
      ${colLabels}
      ${rows}
    </div>`;

  // Stagger cell reveal
  const cells = container.querySelectorAll('.hm-cell');
  cells.forEach((cell, i) => {
    cell.style.opacity = '0';
    cell.style.transform = 'scale(0.7)';
    cell.style.transition = `opacity 0.3s ease ${i * 18}ms, transform 0.3s ease ${i * 18}ms`;
  });
  const hObs = new IntersectionObserver(([e]) => {
    if (e.isIntersecting) {
      cells.forEach(cell => { cell.style.opacity = '1'; cell.style.transform = 'scale(1)'; });
      hObs.disconnect();
    }
  }, { threshold: 0.3 });
  hObs.observe(container);
}

// Init charts
renderPortfolioChart();
renderHeatmap();
