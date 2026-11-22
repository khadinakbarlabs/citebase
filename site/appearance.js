/* Apply the saved appearance before the page paints, including on a return from Apify. */
(function () {
  'use strict';
  const key = 'citebase.appearance';
  const root = document.documentElement;
  let toggle;
  let icon;
  let sprite;

  function apply(theme) {
    const dark = theme === 'dark';
    root.dataset.theme = dark ? 'dark' : 'light';
    const chrome = document.querySelector('meta[name="theme-color"]');
    if (chrome) chrome.content = dark ? '#15121e' : '#faf9ff';
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.title = dark ? 'Use light appearance' : 'Use dark appearance';
      icon.setAttribute('href', sprite + (dark ? '#sun' : '#moon'));
    }
  }

  let saved;
  try { saved = localStorage.getItem(key); } catch { /* Storage is optional. */ }
  apply(saved);
  document.addEventListener('DOMContentLoaded', function () {
    toggle = document.querySelector('[data-theme-toggle]');
    if (!toggle) return;
    icon = toggle.querySelector('use');
    sprite = icon.getAttribute('href').split('#')[0];
    apply(root.dataset.theme);
    toggle.hidden = false;
    toggle.addEventListener('click', function () {
      const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(theme);
      try { localStorage.setItem(key, theme); } catch { /* Keep this page's choice. */ }
    });
  });
  window.addEventListener('storage', function (event) {
    if (event.key === key || event.key === null) apply(event.newValue);
  });
})();

/* Dashboard look preferences (accent, spacing, tips, hidden overview blocks), applied before paint.
   Storage stays here, beside the light/dark choice; app/customize.js only calls window.CitebasePrefs. */
(function () {
  'use strict';
  const key = 'citebase.prefs';
  const root = document.documentElement;
  const accents = ['violet', 'blue', 'teal', 'rose', 'graphite'];
  const blocks = ['journey', 'snapshot', 'focus', 'charts', 'planning'];
  function fresh() { return { accent: 'violet', density: 'comfortable', tips: false, hide: [], projects: 'cards' }; }
  function clean(saved) {
    const s = saved && typeof saved === 'object' ? saved : {};
    return {
      accent: accents.includes(s.accent) ? s.accent : 'violet',
      density: s.density === 'compact' ? 'compact' : 'comfortable',
      tips: s.tips === true,
      hide: Array.isArray(s.hide) ? s.hide.filter(function (k) { return blocks.includes(k); }) : [],
      projects: s.projects === 'table' ? 'table' : 'cards'
    };
  }
  function read() {
    try { return clean(JSON.parse(localStorage.getItem(key) || '{}')); } catch { return fresh(); }
  }
  let prefs = read();
  function apply() {
    root.dataset.accent = prefs.accent;
    root.dataset.density = prefs.density;
    root.dataset.tips = prefs.tips ? 'on' : 'off';
    root.dataset.hide = prefs.hide.join(' ');
  }
  apply();
  window.CitebasePrefs = {
    get: function () { return clean(prefs); },
    set: function (next) {
      prefs = clean(next); apply();
      try { localStorage.setItem(key, JSON.stringify(prefs)); } catch { /* Keep this tab's choice. */ }
    },
    reset: function () { this.set(fresh()); }
  };
  window.addEventListener('storage', function (event) {
    if (event.key === key || event.key === null) { prefs = read(); apply(); }
  });
})();
