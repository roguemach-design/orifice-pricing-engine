"use strict";
document.getElementById("y").textContent = new Date().getFullYear();
const frame = document.getElementById("plate-configurator");
window.addEventListener("message", (event) => {
  if (event.origin !== "https://quote.o-plates.com" || !frame.contentWindow) return;
  let trusted = event.source === frame.contentWindow;
  for (let i = 0; !trusted && i < frame.contentWindow.length; i++) {
    trusted = event.source === frame.contentWindow[i];
  }
  if (!trusted || event.data?.type !== "oplates:height") return;
  const height = event.data.height;
  if (typeof height === "number" && Number.isFinite(height) && height >= 400 && height <= 30000) {
    frame.style.height = `${Math.ceil(height)}px`;
  }
});
document.querySelectorAll('a[href="#configurator"]').forEach((link) => {
  link.addEventListener("click", () => {
    document.getElementById("configurator").focus({preventScroll: true});
  });
});
