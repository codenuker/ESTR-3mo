(() => {
  'use strict';

  const DATA_URL = 'https://raw.githubusercontent.com/codenuker/ESTR-3mo/ecb-liquidity-dashboard-20260906/ecb-liquidity/data/liquidity.json';
  const ENABLED_KEY = 'ecb-excess-liquidity.notifications.enabled.v1';
  const LAST_KEY = 'ecb-excess-liquidity.notifications.last-date.v1';
  const LAST_CHECK_KEY = 'ecb-excess-liquidity.notifications.last-check.v2';
  const LATEST_SEEN_KEY = 'ecb-excess-liquidity.notifications.latest-seen.v2';
  const POLL_MS = 60 * 1000;

  let timer = null;
  let checking = false;
  let swRegistration = null;

  const formatBn = n => Number(n).toLocaleString('en-GB', {minimumFractionDigits: 3, maximumFractionDigits: 3});
  const formatDate = s => {
    const d = new Date(`${s}T00:00:00Z`);
    return Number.isFinite(d.getTime()) ? d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric', timeZone:'UTC'}) : s;
  };
  const formatChecked = s => {
    if (!s) return 'not checked yet';
    const d = new Date(s);
    return Number.isFinite(d.getTime()) ? d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'}) : s;
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
    const r = await fetch(`${DATA_URL}?notify=${Date.now()}`, {
      cache: 'no-store',
      headers: {'Cache-Control': 'no-cache'}
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (d?.schema_version !== 1 || d?.unit !== 'EUR millions' || !Array.isArray(d?.records)) throw new Error('Invalid ECB dataset');
    return d;
  }

  async function ensureServiceWorker() {
    if (!('serviceWorker' in navigator)) return null;
    try {
      if (!swRegistration) swRegistration = await navigator.serviceWorker.register('/notification-sw.js?v=20260917b', {scope:'/'});
      return swRegistration;
    } catch (e) {
      console.warn('ECB alert service worker unavailable:', e);
      return null;
    }
  }

  async function showNotification(title, options) {
    const reg = await ensureServiceWorker();
    if (reg?.showNotification) {
      await reg.showNotification(title, options);
      return;
    }
    const n = new Notification(title, options);
    n.onclick = () => {
      window.focus();
      n.close();
    };
  }

  function updateButton() {
    const b = document.getElementById('notify-toggle');
    const test = document.getElementById('notify-test');
    if (!b) return;

    if (!('Notification' in window)) {
      b.textContent = '🔕 Alerts unsupported';
      b.disabled = true;
      if (test) test.style.display = 'none';
      return;
    }

    const on = enabled() && Notification.permission === 'granted';
    const latest = localStorage.getItem(LATEST_SEEN_KEY) || '—';
    const notified = localStorage.getItem(LAST_KEY) || '—';
    const checked = localStorage.getItem(LAST_CHECK_KEY);
    b.textContent = on ? '🔔 Alerts: ON' : '🔔 Browser Alerts';
    b.classList.toggle('active', on);
    b.title = on
      ? `Alerts enabled · latest dataset ${latest} · last notified/baselined ${notified} · checked ${formatChecked(checked)}`
      : 'Enable browser alerts for new ECB liquidity observations';
    if (test) test.style.display = on ? '' : 'none';
  }

  async function baselineIfNeeded(dataset) {
    const latest = latestRecord(dataset);
    if (!latest?.date) return;
    localStorage.setItem(LATEST_SEEN_KEY, latest.date);
    if (!localStorage.getItem(LAST_KEY)) localStorage.setItem(LAST_KEY, latest.date);
  }

  async function checkForUpdate() {
    if (checking || !enabled() || !('Notification' in window) || Notification.permission !== 'granted') return;
    checking = true;
    try {
      const d = await fetchDataset();
      const latest = latestRecord(d);
      localStorage.setItem(LAST_CHECK_KEY, new Date().toISOString());
      if (!latest?.date || !Number.isFinite(latest.value)) return;

      localStorage.setItem(LATEST_SEEN_KEY, latest.date);
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

      await showNotification('ECB Excess Liquidity Updated', {
        body,
        tag: `ecb-liquidity-${latest.date}`,
        renotify: false,
        icon: '/icon.svg?v=7',
        badge: '/icon.svg?v=7',
        data: {url: '/'}
      });
      localStorage.setItem(LAST_KEY, latest.date);
    } catch (e) {
      console.warn('ECB notification check failed:', e);
    } finally {
      checking = false;
      updateButton();
    }
  }

  async function sendTestAlert() {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    await showNotification('ECB Liquidity Alert Test', {
      body: 'Alerts are enabled on this browser. New ECB observation dates will trigger a notification.',
      tag: `ecb-liquidity-test-${Date.now()}`,
      renotify: false,
      icon: '/icon.svg?v=7',
      badge: '/icon.svg?v=7',
      data: {url: '/'}
    });
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
    await ensureServiceWorker();

    try {
      const d = await fetchDataset();
      localStorage.setItem(LAST_CHECK_KEY, new Date().toISOString());
      await baselineIfNeeded(d);
    } catch (_) {}

    updateButton();
    await sendTestAlert();
    await checkForUpdate();
  }

  function installButtons() {
    if (document.getElementById('notify-toggle')) return;
    const host = document.querySelector('.navright');
    if (!host) return;

    const b = document.createElement('button');
    b.id = 'notify-toggle';
    b.type = 'button';
    b.textContent = '🔔 Browser Alerts';
    b.addEventListener('click', toggleNotifications);

    const test = document.createElement('button');
    test.id = 'notify-test';
    test.type = 'button';
    test.textContent = 'TEST ALERT';
    test.style.display = 'none';
    test.title = 'Send a test browser notification';
    test.addEventListener('click', sendTestAlert);

    const refresh = host.querySelector('#refresh, .primary');
    if (refresh) {
      host.insertBefore(b, refresh);
      host.insertBefore(test, refresh);
    } else {
      host.appendChild(b);
      host.appendChild(test);
    }
    updateButton();
  }

  async function start() {
    installButtons();
    updateButton();
    await ensureServiceWorker();
    if (timer) clearInterval(timer);
    timer = setInterval(checkForUpdate, POLL_MS);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) checkForUpdate();
    });
    window.addEventListener('focus', checkForUpdate);
    window.addEventListener('online', checkForUpdate);
    checkForUpdate();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
