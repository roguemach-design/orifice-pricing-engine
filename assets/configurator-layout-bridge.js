// Display-only bridge for the full-height landing embed. Never reads inputs,
// auth, order data, or invokes pricing. The parent receives rendered feedback.
(() => {
  const app = window.parent;
  const origins = ['https://www.o-plates.com', 'https://o-plates.com'];
  const selector = '.st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child';
  app.__oplatesLayoutCleanup?.();
  let previous = '', scheduled = false;
  const frames = new WeakSet();
  function send() {
    scheduled = false;
    const block = app.document.querySelector('[data-testid="stMainBlockContainer"]');
    if (!block) return;
    const height = Math.ceil(block.getBoundingClientRect().height + 100);
    const column = app.document.querySelector(selector);
    let feedback = null;
    if (column) {
      const rect = column.getBoundingClientRect();
      const main = app.document.querySelector('[data-testid="stMain"]');
      let svg = '';
      for (const frame of column.querySelectorAll('iframe')) {
        if (!frames.has(frame)) { frame.addEventListener('load', schedule); frames.add(frame); }
        try { svg = frame.contentDocument?.querySelector('svg')?.outerHTML || svg; } catch (_) { /* Wait for the existing preview. */ }
      }
      const prices = [...column.querySelectorAll('[data-testid="stMetric"]')].map(metric => ({
        label: metric.querySelector('[data-testid="stMetricLabel"]')?.textContent?.trim() || '',
        value: metric.querySelector('[data-testid="stMetricValue"]')?.textContent?.trim() || ''
      })).filter(metric => metric.label && metric.value).slice(0, 2);
      const captions = [...column.querySelectorAll('[data-testid="stCaptionContainer"]')].map(el => el.textContent.trim());
      const alerts = [...column.querySelectorAll('[data-testid="stAlert"]')].map(el => el.textContent.trim());
      feedback = {
        top: rect.top + (main?.scrollTop || 0), left: rect.left, width: rect.width,
        svg, prices, previewNotice: svg ? '' : (alerts[0] || 'Complete the required dimensions to update the plate preview.'),
        priceNotice: prices.length ? '' : (alerts.at(-1) || 'Complete the required fields to see a verified price.'),
        shipping: captions.filter(text => text.startsWith('Estimated to ship within') || text.startsWith('Shipping estimate')).join(' · ')
      };
    }
    const payload = { type: 'oplates:layout', height, feedback };
    const next = JSON.stringify(payload);
    if (next === previous) return;
    previous = next;
    for (const origin of origins) app.parent.postMessage(payload, origin);
  }
  function schedule() {
    if (!scheduled) { scheduled = true; app.requestAnimationFrame(send); }
  }
  function receive(event) {
    if (!origins.includes(event.origin) || event.source !== app.parent || event.data?.type !== 'oplates:preview-layout') return;
    const enabled = event.data.enabled === true && app.innerWidth >= 901;
    app.document.documentElement.classList.toggle('oplates-parent-preview', enabled);
    const column = app.document.querySelector(selector);
    if (column) { if (enabled) column.setAttribute('aria-hidden', 'true'); else column.removeAttribute('aria-hidden'); }
  }
  const block = app.document.querySelector('[data-testid="stMainBlockContainer"]');
  const resize = new ResizeObserver(schedule);
  const mutations = new MutationObserver(schedule);
  if (block) { resize.observe(block); mutations.observe(block, {childList:true, subtree:true, characterData:true, attributes:true}); }
  app.addEventListener('message', receive);
  app.addEventListener('resize', schedule);
  app.__oplatesLayoutCleanup = () => { resize.disconnect(); mutations.disconnect(); app.removeEventListener('message', receive); app.removeEventListener('resize', schedule); };
  schedule();
})();
