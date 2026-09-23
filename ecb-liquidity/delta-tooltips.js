(() => {
  'use strict';

  const CHART_ID = 'deltachart';
  const TIP_ID = 'delta-hover-tip';

  function getTip() {
    let tip = document.getElementById(TIP_ID);
    if (tip) return tip;
    tip = document.createElement('div');
    tip.id = TIP_ID;
    tip.className = 'tooltip';
    tip.style.display = 'none';
    tip.style.pointerEvents = 'none';
    document.body.appendChild(tip);
    return tip;
  }

  function positionTip(tip, e) {
    const pad = 12;
    const w = tip.offsetWidth || 190;
    const h = tip.offsetHeight || 46;
    let left = e.clientX + pad;
    let top = e.clientY - h - pad;
    if (left + w + 8 > window.innerWidth) left = e.clientX - w - pad;
    if (top < 8) top = e.clientY + pad;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }

  function parseTitle(text) {
    const raw = String(text || '').trim();
    const m = raw.match(/^(.+?):\s*([+-]?[0-9.,-]+)\s*bn$/i);
    if (!m) return null;
    const numeric = Number(m[2].replace(/,/g, ''));
    return {date: m[1], rawValue: m[2], numeric};
  }

  function bindBars() {
    const chart = document.getElementById(CHART_ID);
    if (!chart) return;
    const tip = getTip();

    chart.querySelectorAll('rect').forEach(bar => {
      if (bar.dataset.deltaHoverBound === '1') return;
      const title = bar.querySelector('title');
      const parsed = parseTitle(title?.textContent);
      if (!parsed) return;

      bar.dataset.deltaHoverBound = '1';
      bar.style.cursor = 'crosshair';

      const show = e => {
        const current = parseTitle(title?.textContent) || parsed;
        const n = current.numeric;
        const cls = Number.isFinite(n) ? (n >= 0 ? 'up' : 'down') : '';
        const sign = Number.isFinite(n) && n > 0 && !String(current.rawValue).startsWith('+') ? '+' : '';
        tip.innerHTML = `<strong>${current.date}</strong><br>Daily change: <span class="${cls}">${sign}${current.rawValue} EUR bn</span>`;
        tip.style.display = 'block';
        positionTip(tip, e);
      };

      bar.addEventListener('pointerenter', show);
      bar.addEventListener('pointermove', show);
      bar.addEventListener('pointerleave', () => { tip.style.display = 'none'; });
    });
  }

  function start() {
    const chart = document.getElementById(CHART_ID);
    if (!chart) return;
    bindBars();
    new MutationObserver(bindBars).observe(chart, {childList: true, subtree: true});
    window.addEventListener('blur', () => {
      const tip = document.getElementById(TIP_ID);
      if (tip) tip.style.display = 'none';
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
