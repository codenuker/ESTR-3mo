(() => {
  'use strict';

  const DATA_URL = 'https://raw.githubusercontent.com/codenuker/ESTR-3mo/ecb-liquidity-dashboard-20260906/ecb-liquidity/data/liquidity.json';
  const ENABLED_KEY = 'ecb-excess-liquidity.notifications.enabled.v1';
  const LAST_KEY = 'ecb-excess-liquidity.notifications.last-date.v1';
  const POLL_MS = 60 * 1000;

  let timer = null;
  let checking = false;

  const formatBn = n => Number(n).toLocaleString('en-GB', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const formatDate = s => {
    const d = new Date(`${s}T00:00:00Z`);
    return Number.isFinite(d.getTime()) ? d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric', timeZone:'UTC'}) : s;
  };

  function enabled() {
    return localStorage.getItem(ENABLED_KEY) === '1';
  }

  function latestRecord(dataset) {
    const records = Array.isArray(dataset?.records) ? dataset.records : [];
    return records.length ? records[records.length - 1] : null;
  }

  function previousRecord(dataset) {
    const records = Array.isArray(dataset?.records) ? dataset.records : [];
    return records.length > 1 ? records[records.length - 2] : null;
  }

  async function fetchDataset() {
    const r = await fetch(`${DATA_URL}?notify=${Date.now()}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (d?.schema_version !== 1 || d?.unit !== 'EUR millions' || !Array.isArray(d?.records)) throw new Error('Invalid ECB dataset');
    return d;
  }

  async function baselineLatestDate() {
    try {
      const d = await fetchDataset();
      const latest = latestRecord(d);
      if (latest?.date) localStorage.setItem(LAST_KEY, latest.date);
    } catch (_) {}
  }

  async function checkForUpdate() {
    if (checking || !enabled() || !('Notification' in window) || Notification.permission !== 'granted') return;
    checking = true;
    try {
      const d = await fetchDataset();
      const latest = latestRecord(d);
      if (!latest?.date || !Number.isFinite(latest.value)) return;

      const seen = localStorage.getItem(LAST_KEY);
      if (!seen) {
        localStorage.setItem(LAST_KEY, latest.date);
        return;
      }
      if (latest.date <= seen) return;

      const prev = previousRecord(d);
      const levelBn = latest.value / 1000;
      const changeBn = prev && Number.isFinite(prev.value) ? (latest.value - prev.value) / 1000 : null;
      const direction = changeBn == null ? '' : `${changeBn >= 0 ? '+' : ''}${formatBn(changeBn)}bn DoD`;
      const body = `${formatDate(latest.date)} · €${formatBn(levelBn)}bn${direction ? ` · ${direction}` : ''}`;

      const n = new Notification('ECB Excess Liquidity Updated', {
        body,
        tag: `ecb-liquidity-${latest.date}`,
        renotify: false,
        icon: '/icon.svg?v=5',
        badge: '/icon.svg?v=5'
      });
      n.onclick = () => {
        window.focus();
        n.close();
      };
      localStorage.setItem(LAST_KEY, latest.date);
    } catch (e) {
      console.warn('ECB notification check failed:', e);
    } finally {
      checking = false;
    }
  }

  function updateButton() {
    const b = document.getElementById('notify-toggle');
    if (!b) return;
    if (!('Notification' in window)) {
      b.textContent = '🔕 Alerts unsupported';
      b.disabled = true;
      return;
    }
    const on = enabled() && Notification.permission === 'granted';
    b.textContent = on ? '🔔 Alerts: ON' : '🔔 Browser Alerts';
    b.classList.toggle('active', on);
    b.title = on ? 'Browser alerts are enabled for new ECB liquidity observations' : 'Enable browser alerts for new ECB liquidity observations';
  }

  async function toggleNotifications() {
    if (!('Notification' in window)) return;
    if (enabled() && Notification.permission === 'granted') {
      localStorage.setItem(ENABLED_KEY, '0');
      updateButton();
      return;
    }

    let permission = Notification.permission;
    if (permission === 'default') permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      localStorage.setItem(ENABLED_KEY, '0');
      updateButton();
      return;
    }

    localStorage.setItem(ENABLED_KEY, '1');
    await baselineLatestDate();
    updateButton();
    checkForUpdate();
  }

  function installButton() {
    if (document.getElementById('notify-toggle')) return;
    const host = document.querySelector('.navright');
    if (!host) return;
    const b = document.createElement('button');
    b.id = 'notify-toggle';
    b.type = 'button';
    b.textContent = '🔔 Browser Alerts';
    b.addEventListener('click', toggleNotifications);
    const refresh = host.querySelector('#refresh, .primary');
    if (refresh) host.insertBefore(b, refresh);
    else host.appendChild(b);
    updateButton();
  }

  function start() {
    installButton();
    updateButton();
    if (timer) clearInterval(timer);
    timer = setInterval(checkForUpdate, POLL_MS);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkForUpdate();
    });
    window.addEventListener('focus', checkForUpdate);
    checkForUpdate();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
