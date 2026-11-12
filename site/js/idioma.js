// Language choice, before anything is painted (ADR-037). Classic script, loaded in <head> by every page.
// Order: ?lang=en|es, then the choice saved by the header switch (localStorage), then the browser language
// (anything that does not start with "es" reads English). The dictionary and the translation itself live in
// js/i18n.js; this file only decides, sets <html lang> and hides the Spanish text until the English one is in.
(function () {
  var lang = null, explicito = false;
  try {
    var q = new URLSearchParams(window.location.search).get("lang");
    if (q === "en" || q === "es") {
      lang = q;
      explicito = true;
    }
  } catch (e) { /* very old browser: fall through */ }
  if (!lang) {
    try {
      var g = window.localStorage.getItem("vma-lang");
      if (g === "en" || g === "es") lang = g;
    } catch (e) { /* storage blocked: fall through */ }
  }
  if (!lang) lang = String(window.navigator.language || "es").toLowerCase().indexOf("es") === 0 ? "es" : "en";
  window.__VMA_LANG = lang;
  window.__VMA_LANG_EXPLICITO = explicito;
  var raiz = document.documentElement;
  raiz.lang = lang;
  if (lang !== "es") {
    raiz.classList.add("traduciendo"); // css: body hidden; i18n.js removes it once the page is translated
    window.setTimeout(function () { raiz.classList.remove("traduciendo"); }, 2500); // never leave a page blank
  }
})();
