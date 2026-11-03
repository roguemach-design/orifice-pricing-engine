import { getDocument, GlobalWorkerOptions } from "./vendor/pdf.min.mjs";
let workerURL = null;
async function prepareWorker() {
  if (workerURL) return;
  const response = await fetch(
    new URL("./vendor/pdf.worker.min.mjs.gz", import.meta.url),
  );
  if (!response.ok) throw Error("PDF worker unavailable");
  const content = await new Response(
    response.body.pipeThrough(new DecompressionStream("gzip")),
  ).arrayBuffer();
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", content)),
    (v) => v.toString(16).padStart(2, "0"),
  ).join("");
  if (
    digest !==
    "1e64c8240e54735ec5913b37acd5134747799cb8c6bb3777c70adbc01232d2aa"
  )
    throw Error("PDF worker integrity");
  workerURL = URL.createObjectURL(
    new Blob([content], { type: "text/javascript" }),
  );
  GlobalWorkerOptions.workerSrc = workerURL;
}
const $ = (id) => document.getElementById(id);
const viewer = $("viewer"),
  surface = $("surface"),
  canvas = $("page"),
  status = $("status");
let documentPDF = null,
  task = null,
  renderTask = null,
  bytes = null,
  blobURL = null,
  identity = "",
  generation = 0;
let pageNumber = 1,
  scale = 1,
  baseScale = 1,
  rendering = Promise.resolve(),
  renderSerial = 0;
function send(type, extra = {}) {
  parent.postMessage({ isStreamlitMessage: true, type, ...extra }, "*");
}
let lastHeight = 0;
function height() {
  const value = viewer.scrollHeight + 2;
  if (!document.fullscreenElement && value !== lastHeight) {
    lastHeight = value;
    send("streamlit:setFrameHeight", { height: value });
  }
}
function message(text) {
  status.textContent = text;
  height();
}
function cleanup() {
  generation++;
  renderTask?.cancel();
  renderTask = null;
  task?.destroy();
  task = null;
  documentPDF = null;
  bytes = null;
  if (blobURL) URL.revokeObjectURL(blobURL);
  blobURL = null;
  canvas.width = 0;
  canvas.height = 0;
  $("download").disabled = true;
  identity = "";
  if (workerURL) URL.revokeObjectURL(workerURL);
  workerURL = null;
}
async function draw(fit = false) {
  const version = generation,
    serial = ++renderSerial,
    doc = documentPDF;
  if (!doc) return;
  message("Rendering drawing page…");
  rendering = rendering
    .catch(() => {})
    .then(async () => {
      if (version !== generation || serial !== renderSerial) return;
      const page = await doc.getPage(pageNumber);
      if (version !== generation) return;
      if (fit) {
        const viewport = page.getViewport({ scale: 1 });
        baseScale = Math.min(
          (surface.clientWidth - 28) / viewport.width,
          (surface.clientHeight - 28) / viewport.height,
        );
        scale = 1;
        surface.scrollTo(0, 0);
      }
      const viewport = page.getViewport({ scale: baseScale * scale });
      const ratio = Math.min(devicePixelRatio || 1, 2);
      // Bound canvas memory; vector PDF is rerendered at each zoom, never a screenshot.
      const pixels = Math.min(
        ratio,
        Math.sqrt(16000000 / (viewport.width * viewport.height)),
      );
      canvas.width = Math.ceil(viewport.width * pixels);
      canvas.height = Math.ceil(viewport.height * pixels);
      canvas.style.width = viewport.width + "px";
      canvas.style.height = viewport.height + "px";
      renderTask = page.render({
        canvasContext: canvas.getContext("2d"),
        viewport,
        transform: [pixels, 0, 0, pixels, 0, 0],
      });
      await renderTask.promise;
      renderTask = null;
      if (version !== generation || serial !== renderSerial) return;
      $("pages").textContent = `Page ${pageNumber} / ${doc.numPages}`;
      $("zoom").textContent = Math.round(scale * 100) + "%";
      $("previous").disabled = pageNumber <= 1;
      $("next").disabled = pageNumber >= doc.numPages;
      canvas.setAttribute(
        "aria-label",
        `Stored approved engineering drawing, page ${pageNumber} of ${doc.numPages}`,
      );
      message("Verified stored PDF · " + $("pages").textContent);
      height();
    })
    .catch((error) => {
      if (
        version === generation &&
        error.name !== "RenderingCancelledException"
      )
        message(
          "Preview unavailable. Download the verified PDF to view every page.",
        );
    });
  return rendering;
}
async function load(args) {
  const next = args.revision + ":" + args.digest;
  if (identity === next) return;
  cleanup();
  identity = next;
  const version = generation;
  message("Verifying stored drawing…");
  try {
    const decoded = Uint8Array.from(atob(args.pdf), (c) => c.charCodeAt(0));
    if (decoded.length !== args.size) throw Error("size");
    const hash = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", decoded)),
      (v) => v.toString(16).padStart(2, "0"),
    ).join("");
    if (hash !== args.digest) throw Error("hash");
    if (version !== generation) return;
    bytes = decoded;
    blobURL = URL.createObjectURL(
      new Blob([bytes], { type: "application/pdf" }),
    );
    $("download").disabled = false;
    $("download").onclick = () => {
      if (!blobURL) return;
      const a = document.createElement("a");
      a.href = blobURL;
      a.download = args.filename.replace(/[/\\]/g, "_");
      a.click();
    };
    await prepareWorker();
    if (version !== generation) return;
    task = getDocument({
      data: bytes.slice(),
      isEvalSupported: false,
      useSystemFonts: true,
      disableAutoFetch: true,
      disableStream: true,
      enableXfa: false,
    });
    const doc = await task.promise;
    if (version !== generation) {
      doc.destroy();
      return;
    }
    documentPDF = doc;
    pageNumber = 1;
    await draw(true);
  } catch (error) {
    if (version !== generation) return;
    if (bytes)
      message(
        "Preview unavailable. Download the verified PDF to view every page.",
      );
    else {
      cleanup();
      message("Drawing verification failed. No file is available.");
    }
  }
}
$("previous").onclick = () => {
  if (documentPDF && pageNumber > 1) {
    pageNumber--;
    draw(true);
  }
};
$("next").onclick = () => {
  if (documentPDF && pageNumber < documentPDF.numPages) {
    pageNumber++;
    draw(true);
  }
};
function zoom(factor) {
  scale = Math.max(0.5, Math.min(6, scale * factor));
  draw();
}
$("in").onclick = () => zoom(1.25);
$("out").onclick = () => zoom(0.8);
$("fit").onclick = () => draw(true);
$("full").onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await viewer.requestFullscreen();
  } catch {
    message(
      "Full-screen is unavailable in this browser or website frame. Download the verified PDF for full-screen viewing.",
    );
  }
};
document.addEventListener("fullscreenchange", () => {
  $("full").textContent = document.fullscreenElement
    ? "Exit full screen"
    : "Full screen";
  draw(true);
  height();
});
const pointers = new Map();
let gesture = null;
surface.addEventListener("pointerdown", (event) => {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  surface.setPointerCapture(event.pointerId);
  surface.classList.add("dragging");
  gesture = null;
});
surface.addEventListener("pointermove", (event) => {
  if (!pointers.has(event.pointerId)) return;
  const old = pointers.get(event.pointerId);
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  const pts = [...pointers.values()];
  if (pts.length === 2) {
    const distance = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    if (gesture) zoom(distance / gesture);
    gesture = distance;
  } else {
    surface.scrollLeft -= event.clientX - old.x;
    surface.scrollTop -= event.clientY - old.y;
  }
});
for (const type of ["pointerup", "pointercancel", "lostpointercapture"])
  surface.addEventListener(type, (event) => {
    pointers.delete(event.pointerId);
    gesture = null;
    if (!pointers.size) surface.classList.remove("dragging");
  });
surface.addEventListener(
  "wheel",
  (event) => {
    if (event.ctrlKey) {
      event.preventDefault();
      zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
    }
  },
  { passive: false },
);
surface.addEventListener("keydown", (event) => {
  if (event.key === "+") {
    event.preventDefault();
    zoom(1.25);
  } else if (event.key === "-") {
    event.preventDefault();
    zoom(0.8);
  } else if (event.key === "0") {
    event.preventDefault();
    draw(true);
  }
});
let resizeTimer,
  lastSize = "";
new ResizeObserver(() => {
  const size = surface.clientWidth + ":" + surface.clientHeight;
  if (size === lastSize) return;
  lastSize = size;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (documentPDF) draw(true);
    height();
  }, 100);
}).observe(surface);
addEventListener("message", (event) => {
  if (event.source === parent && event.data?.type === "streamlit:render") {
    setTimeout(() => {
      lastHeight = 0;
      height();
    }, 0);
    load(event.data.args);
  }
});
addEventListener("pagehide", cleanup);
addEventListener("beforeunload", cleanup);
send("streamlit:componentReady", { apiVersion: 1 });
height();
