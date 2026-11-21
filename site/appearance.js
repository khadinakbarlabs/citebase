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
