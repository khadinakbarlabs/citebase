/* Citebase traffic source labels for the Google Analytics report.
   Mirrors connector/signals.py (AI_REFERRERS, BARE_NAMES, RETURN_HOSTS); tests/test_traffic_sources.py keeps them equal.
   The server labels synced rows itself; this copy labels rows from a server that has not been updated yet. */
(function () {
  'use strict';
  var CB = window.CB;
  var AI_REFERRERS = {
    'chatgpt.com': 'ChatGPT', 'chat.openai.com': 'ChatGPT', 'openai.com': 'ChatGPT',
    'perplexity.ai': 'Perplexity', 'claude.ai': 'Claude', 'gemini.google.com': 'Gemini',
    'copilot.microsoft.com': 'Copilot', 'copilot.com': 'Copilot', 'you.com': 'You.com', 'phind.com': 'Phind',
    'meta.ai': 'Meta AI', 'grok.com': 'Grok', 'chat.mistral.ai': 'Mistral', 'chat.deepseek.com': 'DeepSeek',
    'duckduckgo.com/aichat': 'DuckDuckGo AI'
  };
  var BARE_NAMES = { chatgpt: 'ChatGPT', perplexity: 'Perplexity', claude: 'Claude', gemini: 'Gemini',
    copilot: 'Copilot', grok: 'Grok', deepseek: 'DeepSeek' };
  var RETURN_HOSTS = {
    'checkout.stripe.com': 'Stripe checkout', 'billing.stripe.com': 'Stripe billing', 'buy.stripe.com': 'Stripe checkout',
    'pay.stripe.com': 'Stripe checkout', 'invoice.stripe.com': 'Stripe billing',
    'paypal.com': 'PayPal', 'checkout.paypal.com': 'PayPal',
    'accounts.google.com': 'Google sign-in', 'appleid.apple.com': 'Apple sign-in',
    'login.microsoftonline.com': 'Microsoft sign-in', 'login.live.com': 'Microsoft sign-in',
    'checkout.shopify.com': 'Shopify checkout', 'app.lemonsqueezy.com': 'Lemon Squeezy checkout'
  };

  function clean(value) {
    return String(value == null ? '' : value).trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '');
  }
  function escape(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // The assistant a source belongs to ('chatgpt.com / referral' -> 'ChatGPT'), else null.
  function aiSource(value) {
    var text = clean(value);
    if (Object.prototype.hasOwnProperty.call(BARE_NAMES, text)) return BARE_NAMES[text];
    for (var host in AI_REFERRERS) {
      if (new RegExp('^([a-z0-9-]+\\.)*' + escape(host) + '(\\s|/|\\?|$)').test(text)) return AI_REFERRERS[host];
    }
    return null;
  }
  // The checkout or sign-in page a returning visitor came back from ('checkout.stripe.com' -> 'Stripe checkout'), else null.
  function returnSource(value) {
    var host = clean(value).split(/[\s/?]/)[0];
    for (var known in RETURN_HOSTS) {
      if (host === known || host.slice(-known.length - 1) === '.' + known) return RETURN_HOSTS[known];
    }
    return null;
  }
  // Server labels win; otherwise label the row here.
  function label(row) {
    var assistant = row && typeof row.assistant === 'string' ? row.assistant : null;
    var back = row && typeof row.returning_from === 'string' ? row.returning_from : null;
    if (assistant || back) return { assistant: assistant, returningFrom: back };
    assistant = aiSource(row && row.source);
    return { assistant: assistant, returningFrom: assistant ? null : returnSource(row && row.source) };
  }

  CB.trafficSources = { aiSource: aiSource, returnSource: returnSource, label: label };
})();
