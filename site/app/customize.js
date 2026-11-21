/* Citebase dashboard Customize panel: accent colour, density, tips and which overview blocks show.
   ../appearance.js keeps the choice in this browser and applies it before the page paints.
   Section explanations collapse into small "?" buttons unless tips are on. */
(function () {
  'use strict';
  var ACCENTS = [['violet', 'Violet', '#6d31ed'], ['blue', 'Blue', '#2a62e8'], ['teal', 'Teal', '#0e8577'],
    ['rose', 'Rose', '#d12c6c'], ['graphite', 'Graphite', '#2f2b36']];
  var BLOCKS = [['snapshot', 'Visibility snapshot'], ['focus', 'What to do next'], ['charts', 'Trend and engine charts'],
    ['planning', 'Project planning']];
  // Saved and applied before paint by ../appearance.js (window.CitebasePrefs).
  var store = window.CitebasePrefs || { get: function () { return { accent: 'violet', density: 'comfortable', tips: false, hide: [] }; },
    set: function () {}, reset: function () {} };
  var prefs = store.get();
  function save() { store.set(prefs); }

  document.addEventListener('DOMContentLoaded', function () {
    var CB = window.CB, h = CB.h;
    var opener = document.querySelector('.customize-open');

    /* ---------- the panel ---------- */
    function choice(label, options, value, onpick) {
      var group = h('div', { class: 'cz-seg', role: 'radiogroup', 'aria-label': label });
      options.forEach(function (o) {
        var b = h('button', { type: 'button', role: 'radio', 'aria-checked': String(o[0] === value) },
          o[2] ? h('i', { class: 'cz-dot cz-' + o[0], 'aria-hidden': 'true' }) : null, h('span', { text: o[1] }));
        b.addEventListener('click', function () {
          group.querySelectorAll('[role=radio]').forEach(function (x) { x.setAttribute('aria-checked', String(x === b)); });
          onpick(o[0]);
        });
        group.appendChild(b);
      });
      return h('div', { class: 'cz-row' }, h('span', { class: 'cz-label', text: label }), group);
    }
    function toggle(label, hint, on, onflip) {
      var input = h('input', { type: 'checkbox', role: 'switch' });
      input.checked = on;
      input.addEventListener('change', function () { onflip(input.checked); });
      return h('label', { class: 'cz-switch' }, h('span', { class: 'cz-switch-text' }, h('b', { text: label }), hint ? h('small', { text: hint }) : null),
        input, h('i', { class: 'cz-track', 'aria-hidden': 'true' }));
    }
    function panel() {
      var dlg = h('dialog', { class: 'cz-panel', 'aria-labelledby': 'cz-title' });
      function close() {
        dlg.classList.add('closing');
        setTimeout(function () { if (dlg.open) dlg.close(); dlg.remove(); if (opener) opener.focus(); }, 180);
      }
      var body = h('div', { class: 'cz-body' },
        choice('Accent colour', ACCENTS, prefs.accent, function (v) { prefs.accent = v; save(); }),
        choice('Spacing', [['comfortable', 'Roomy'], ['compact', 'Compact']], prefs.density, function (v) { prefs.density = v; save(); }),
        toggle('Show tips', 'A short line under each section explains it. Off keeps tips behind the ? buttons.', prefs.tips,
          function (v) { prefs.tips = v; save(); }),
        h('div', { class: 'cz-row' }, h('span', { class: 'cz-label', text: 'Project overview shows' }),
          h('div', { class: 'cz-blocks' }, BLOCKS.map(function (b) {
            return toggle(b[1], null, prefs.hide.indexOf(b[0]) < 0, function (on) {
              prefs.hide = prefs.hide.filter(function (k) { return k !== b[0]; });
              if (!on) prefs.hide.push(b[0]);
              save();
            });
          }))));
      dlg.append(
        h('header', { class: 'cz-head' }, h('h2', { id: 'cz-title', text: 'Customize' }),
          h('button', { type: 'button', class: 'cz-x', 'aria-label': 'Close', onclick: close }, CB.icon('x'))),
        body,
        h('footer', { class: 'cz-foot' },
          h('button', { type: 'button', class: 'btn ghost', text: 'Reset', onclick: function () {
            store.reset(); prefs = store.get(); dlg.close(); dlg.remove(); open(); CB.toast('Back to the default look', { tone: 'info' });
          } }),
          h('button', { type: 'button', class: 'btn', text: 'Done', onclick: close })));
      dlg.addEventListener('cancel', function (e) { e.preventDefault(); close(); });
      dlg.addEventListener('click', function (e) { if (e.target === dlg) close(); });
      return dlg;
    }
    function open() {
      prefs = store.get();
      var dlg = panel();
      document.body.appendChild(dlg);
      dlg.showModal();
    }
    if (opener) opener.addEventListener('click', open);

    /* ---------- section explanations become one-tap "?" buttons ---------- */
    var seq = 0;
    function addInfo(sub) {
      sub.dataset.info = '1';
      var top = sub.closest('.card-top');
      var heading = top && top.querySelector('h2, h3');
      if (!heading) return;
      if (!sub.id) sub.id = 'cz-sub-' + (++seq);
      var btn = h('button', { type: 'button', class: 'info-dot', 'aria-expanded': 'false', 'aria-controls': sub.id,
        'aria-label': 'About ' + heading.textContent, title: 'What is this?' }, CB.icon('help', 'fb-icon sm'));
      btn.addEventListener('click', function () {
        btn.setAttribute('aria-expanded', String(sub.classList.toggle('reveal')));
      });
      heading.classList.add('has-info');
      heading.insertAdjacentElement('afterend', btn);
    }
    var main = document.getElementById('main');
    if (main) new MutationObserver(function () {
      main.querySelectorAll('.card-top .sub:not([data-info])').forEach(addInfo);
    }).observe(main, { childList: true, subtree: true });
  });
})();
