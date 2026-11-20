/* All sample readings and links are in the page, including when scripting is unavailable. */
(function () {
  'use strict';

  function setupAccountLinks() {
    const account = window.CitebaseSession;
    if (!account) return;
    const accountLinks = Array.from(document.querySelectorAll('[data-account-link]'), link => ({
      link, label: link.querySelector('[data-account-label]'), start: link.getAttribute('href')
    }));
    accountLinks.forEach(item => { item.signedOutLabel = item.label.textContent; });
    const hosted = accountLinks[0].start === account.start;
    const dashboardRoutes = document.querySelectorAll('[data-account-route]');
    const hint = document.querySelector('[data-signin-hint]');
    const signedOutHint = hint.textContent;
    let checking = null;
    function showAccount(signedIn) {
      for (const item of accountLinks) {
        item.link.setAttribute('href', signedIn ? 'app/' : item.start);
        item.label.textContent = signedIn ? 'Dashboard' : item.signedOutLabel;
      }
      for (const link of dashboardRoutes) link.setAttribute('href', signedIn ? 'app/' : accountLinks[0].start);
      hint.textContent = signedIn ? 'Your Apify workspace is connected. Open the dashboard to continue, or explore the sample tour.' : signedOutHint;
      return signedIn;
    }
    function checkAccount() {
      if (!hosted) return Promise.resolve(showAccount(Boolean(account.stored('cb.t'))));
      if (!checking) checking = account.request('status').then(result => showAccount(result.signedIn))
        .catch(() => null).finally(() => { checking = null; });
      return checking;
    }
    // Let a pre-upgrade tab finish moving its existing sign-in before following the CTA.
    for (const link of document.querySelectorAll('[data-account-link], [data-account-route]')) link.addEventListener('click', async event => {
      if (!hosted || !account.stored('cb.t') && !account.stored('cb.r')
          || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      location.assign(await checkAccount() ? 'app/' : accountLinks[0].start);
    });
    window.addEventListener('pageshow', event => { if (event.persisted) checkAccount(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) checkAccount(); });
    account.onChange(checkAccount);
    checkAccount();
  }
  setupAccountLinks();

  const mobileNav = document.querySelector('.mobile-navigation');
  mobileNav.addEventListener('click', function (event) {
    if (event.target.closest('a')) mobileNav.open = false;
  });
  mobileNav.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && mobileNav.open) {
      mobileNav.open = false;
      mobileNav.querySelector('summary').focus();
    }
  });
  document.addEventListener('pointerdown', function (event) {
    if (mobileNav.open && !mobileNav.contains(event.target)) mobileNav.open = false;
  });

  const bench = document.getElementById('examples');
  const projects = bench.querySelector('.project-picker');
  const tablist = bench.querySelector('.sample-tabs');
  const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  const stories = bench.querySelectorAll('.sample-story');
  const compactTabs = window.matchMedia('(max-width: 700px)');
  function syncOrientation() {
    tablist.setAttribute('aria-orientation', compactTabs.matches ? 'horizontal' : 'vertical');
  }
  compactTabs.addEventListener('change', syncOrientation);
  syncOrientation();
  let stage = 'question';

  function showStage() {
    const project = projects.querySelector('input:checked').value;
    for (const tab of tabs) {
      const selected = tab.dataset.view === stage;
      tab.setAttribute('aria-selected', String(selected));
      tab.setAttribute('aria-controls', project + '-' + tab.dataset.view);
      tab.tabIndex = selected ? 0 : -1;
    }
    for (const story of stories) {
      story.hidden = story.id !== 'sample-' + project;
      for (const panel of story.querySelectorAll('[data-stage]')) {
        panel.hidden = panel.dataset.stage !== stage;
        panel.setAttribute('role', 'tabpanel');
        panel.setAttribute('aria-labelledby', 'tab-' + panel.dataset.stage);
        panel.tabIndex = 0;
      }
    }
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () {
      stage = tab.dataset.view;
      showStage();
    });
    tab.addEventListener('keydown', function (event) {
      let next;
      switch (event.key) {
        case 'ArrowDown':
          if (compactTabs.matches) return;
          next = (index + 1) % tabs.length; break;
        case 'ArrowUp':
          if (compactTabs.matches) return;
          next = (index + tabs.length - 1) % tabs.length; break;
        case 'ArrowRight': next = (index + 1) % tabs.length; break;
        case 'ArrowLeft': next = (index + tabs.length - 1) % tabs.length; break;
        case 'Home': next = 0; break;
        case 'End': next = tabs.length - 1; break;
        default: return;
      }
      event.preventDefault();
      stage = tabs[next].dataset.view;
      showStage();
      tabs[next].focus();
    });
  });
  projects.addEventListener('change', function () {
    showStage();
    const projectName = projects.querySelector('input:checked').nextElementSibling.textContent.trim();
    const tabName = tabs.find(tab => tab.dataset.view === stage).textContent;
    document.getElementById('sample-status').textContent = projectName + ', ' + tabName + '.';
  });
  showStage();
  // History navigation can restore a native radio choice after the script first ran.
  window.addEventListener('pageshow', showStage);
  bench.classList.add('is-interactive');
  projects.hidden = false;
  tablist.hidden = false;

  for (const button of document.querySelectorAll('[data-copy]')) {
    const code = document.getElementById(button.dataset.copy);
    const status = button.closest('article').querySelector('.copy-result');
    button.hidden = false;
    button.addEventListener('click', async function () {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          await navigator.clipboard.writeText(code.textContent);
          status.textContent = 'Copied to clipboard.';
          return;
        } catch {
          // A browser may disable the clipboard or deny access. Leave the exact text selectable.
        }
      }
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(code);
        selection.removeAllRanges();
        selection.addRange(range);
        status.textContent = 'Text selected. Use your device’s Copy command.';
      } else {
        status.textContent = 'Select the text and use your device’s Copy command.';
      }
    });
  }
})();
