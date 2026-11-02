/* The MCP Apps bridge (spec 2026-01-26): JSON-RPC 2.0 over postMessage, no SDK (ADR-032).
   Injected into every ui://vaca-muerta/ resource at the PUENTE marker by vma/apps/__init__.py. */
(function () {
  const pend = {};
  let nextId = 0;
  const send = (msg) => window.parent.postMessage(msg, "*");
  const request = (method, params) =>
    new Promise((res, rej) => {
      const id = ++nextId;
      pend[id] = { res, rej };
      send({ jsonrpc: "2.0", id, method, params: params || {} });
    });
  const notify = (method, params) => send({ jsonrpc: "2.0", method, params: params || {} });
  const App = {
    ctx: {},
    enHost: window.parent !== window,
    onResult: null,
    onInput: null,
    onContext: null,
    request,
    notify,
    callTool: (name, args) => request("tools/call", { name, arguments: args || {} }),
    message: (text) => request("ui/message", { role: "user", content: { type: "text", text } }),
    openLink: (url) => request("ui/open-link", { url }),
    parse(result) {
      if (!result) return null;
      if (result.structuredContent && result.structuredContent.datos) return result.structuredContent;
      const t = (result.content || []).find((c) => c.type === "text");
      if (!t) return result.structuredContent || null;
      try {
        return JSON.parse(t.text);
      } catch (e) {
        return null;
      }
    },
  };
  window.addEventListener("message", (ev) => {
    const m = ev.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id !== undefined && m.method === undefined) {
      const p = pend[m.id];
      if (!p) return;
      delete pend[m.id];
      m.error ? p.rej(m.error) : p.res(m.result);
      return;
    }
    if (m.method === "ui/notifications/tool-result") App.onResult && App.onResult(m.params);
    else if (m.method === "ui/notifications/tool-input") App.onInput && App.onInput((m.params || {}).arguments || {});
    else if (m.method === "ui/notifications/tool-input-partial") App.onInputPartial && App.onInputPartial((m.params || {}).arguments || {});
    else if (m.method === "ui/notifications/tool-cancelled") App.onCancelled && App.onCancelled(m.params);
    else if (m.method === "ui/notifications/host-context-changed") {
      Object.assign(App.ctx, m.params || {});
      App.aplicarTema();
      App.onContext && App.onContext(App.ctx);
    } else if (m.method === "ui/resource-teardown") send({ jsonrpc: "2.0", id: m.id, result: {} });
    else if (m.method === "ping") send({ jsonrpc: "2.0", id: m.id, result: {} });
  });
  App.aplicarTema = function () {
    const t = App.ctx.theme;
    if (t) document.documentElement.setAttribute("data-theme", t);
    const vars = (App.ctx.styles && App.ctx.styles.variables) || {};
    for (const k in vars) document.documentElement.style.setProperty(k, vars[k]);
  };
  App.start = async function () {
    if (!App.enHost) return App.ctx; // opened as a plain page: nothing to talk to
    const r = await request("ui/initialize", {
      protocolVersion: "2026-01-26",
      appInfo: { name: "vaca-muerta-abierta", version: "0.1.0" },
      clientInfo: { name: "vaca-muerta-abierta", version: "0.1.0" },
      appCapabilities: { availableDisplayModes: ["inline"] },
    });
    Object.assign(App.ctx, (r && r.hostContext) || {});
    App.aplicarTema();
    notify("ui/notifications/initialized", {});
    // body height, not documentElement.scrollHeight: the latter never shrinks below the iframe's own height
    const medir = () =>
      notify("ui/notifications/size-changed", {
        width: Math.ceil(document.body.getBoundingClientRect().width),
        height: Math.ceil(document.body.getBoundingClientRect().height),
      });
    new ResizeObserver(medir).observe(document.body);
    medir();
    return App.ctx;
  };
  App.fmt = (x, d) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toLocaleString("es-AR", { maximumSignificantDigits: d || 4 }));
  window.VMA = App;
})();
