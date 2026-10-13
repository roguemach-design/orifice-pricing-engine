"use strict";
document.getElementById("y").textContent = new Date().getFullYear();
const frame = document.getElementById("plate-configurator");
const stage = document.getElementById("configurator-stage");
const rail = document.getElementById("configurator-feedback");
let feedback = null;
function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}
function safeSvg(markup) {
  if (typeof markup !== 'string' || markup.length > 200000) return null;
  const parsed = new DOMParser().parseFromString(markup, 'image/svg+xml');
  const svg = parsed.documentElement;
  if (svg.localName !== 'svg' || parsed.querySelector('parsererror')) return null;
  svg.querySelectorAll('script,foreignObject,style,image,use,a').forEach(el => el.remove());
  [svg, ...svg.querySelectorAll('*')].forEach(el => {
    [...el.attributes].forEach(attr => {
      if (/^on/i.test(attr.name) || /href$|^src$/i.test(attr.name)) el.removeAttribute(attr.name);
    });
  });
  return document.importNode(svg, true);
}
function syncLayout() {
  if (!stage || !rail) return;
  const enabled = Boolean(feedback && window.innerWidth >= 901 && frame.clientWidth >= 901);
  rail.hidden = !enabled;
  stage.classList.toggle('has-sticky-feedback', enabled);
  if (enabled) {
    const header = document.querySelector('.topbar');
    stage.style.setProperty('--preview-top', `${Math.ceil(header?.getBoundingClientRect().height || 64) + 12}px`);
    rail.style.marginTop = `${frame.offsetTop + feedback.top}px`;
    rail.style.marginLeft = `${frame.offsetLeft + feedback.left}px`;
    rail.style.width = `${feedback.width}px`;
  }
  frame.contentWindow?.postMessage({type:'oplates:preview-layout', enabled}, 'https://quote.o-plates.com');
}
// Elevate the existing iframe; moving it into a new DOM parent would reset auth UI state.
function syncModal(open) {
  if (!stage || typeof open !== 'boolean') return;
  const active = document.documentElement.classList.contains('oplates-modal-open');
  if (open === active) return;
  if (open) stage.style.setProperty('--modal-stage-height', `${stage.getBoundingClientRect().height}px`);
  document.documentElement.classList.toggle('oplates-modal-open', open);
}
function renderFeedback(data) {
  if (!rail || !stage || !data || ![data.top, data.left, data.width].every(Number.isFinite) || data.top < 0 || data.top > 30000 || data.left < 0 || data.width < 100 || data.width > frame.clientWidth) return;
  if (!Array.isArray(data.prices) || data.prices.length > 2 || data.prices.some(item => !item || typeof item.label !== 'string' || typeof item.value !== 'string' || item.label.length > 100 || item.value.length > 100)) return;
  if (![data.previewNotice, data.priceNotice, data.shipping].every(value => typeof value === 'string' && value.length <= 2000)) return;
  const fulfillment = data.fulfillment || [];
  if (!Array.isArray(fulfillment) || fulfillment.length > 3 || fulfillment.some(item => !item || !['Estimated ship time', 'Estimated total weight', 'Estimated package'].includes(item.label) || typeof item.value !== 'string' || item.value.length > 100)) return;
  const svg = safeSvg(data.svg);
  if (data.svg && !svg) return;
  rail.replaceChildren(textElement('h3', 'Configuration Drawing'));
  if (svg) {
    const drawing = document.createElement('div');
    drawing.className = 'sticky-feedback__drawing'; drawing.append(svg); rail.append(drawing);
  } else rail.append(textElement('p', data.previewNotice, 'muted'));
  const price = document.createElement('div'); price.className = 'sticky-feedback__price';
  if (data.prices.length) {
    for (const item of data.prices) {
      const metric = document.createElement('div');
      metric.append(textElement('span', item.label), textElement('strong', item.value)); price.append(metric);
    }
  } else price.append(textElement('p', data.priceNotice, 'muted'));
  rail.append(price);
  if (fulfillment.length) {
    const summary = document.createElement('div'); summary.className = 'sticky-feedback__fulfillment';
    const shipping = document.createElement('div'); shipping.className = 'sticky-feedback__estimates';
    for (const item of fulfillment) {
      const metric = document.createElement('div');
      metric.append(textElement('span', item.label), textElement('strong', item.value));
      if (item.label === 'Estimated ship time') summary.append(metric);
      else shipping.append(metric);
    }
    summary.append(textElement('h4', 'Shipping estimates'), shipping); rail.append(summary);
  } else if (data.shipping) rail.append(textElement('p', data.shipping, 'sticky-feedback__shipping'));
  feedback = data;
  syncLayout();
}
window.addEventListener("message", (event) => {
  if (event.origin !== "https://quote.o-plates.com" || !frame.contentWindow) return;
  let trusted = event.source === frame.contentWindow;
  for (let i = 0; !trusted && i < frame.contentWindow.length; i++) trusted = event.source === frame.contentWindow[i];
  if (!trusted || !['oplates:height', 'oplates:layout'].includes(event.data?.type)) return;
  syncModal(event.data.modalOpen);
  const height = event.data.height;
  if (!document.documentElement.classList.contains('oplates-modal-open') && typeof height === "number" && Number.isFinite(height) && height >= 400 && height <= 30000) frame.style.height = `${Math.ceil(height)}px`;
  if (event.data.type === 'oplates:layout' && event.data.modalOpen !== true) {
    if (event.data.feedback === null) { feedback = null; rail?.replaceChildren(); syncLayout(); }
    else renderFeedback(event.data.feedback);
  }
});
window.addEventListener('resize', syncLayout);
if (typeof ResizeObserver !== 'undefined' && stage) new ResizeObserver(syncLayout).observe(stage);
document.querySelectorAll('a[href="#configurator"]').forEach((link) => {
  link.addEventListener("click", () => document.getElementById("configurator").focus({preventScroll: true}));
});
