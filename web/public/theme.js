// Resolve the theme before first paint, so the page never flashes the wrong one.
// A file rather than an inline <script>: the Content-Security-Policy allows
// scripts from this origin only, and an inline exception would be one more
// thing an injected script could hide behind.
(function () {
  try {
    var t = localStorage.getItem("atom.theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch (e) {
    /* storage blocked: follow the OS */
  }
})();
