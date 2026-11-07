(function () {
    "use strict";
    var el = document.getElementById("engine-status");
    if (!el) { return; }
    async function refresh() {
        try {
            var r = await fetch("/api/status", { credentials: "same-origin", headers: { "Accept": "application/json" } });
            if (r.status === 401) { window.location.href = "/login"; return; }
            if (!r.ok) { return; }
            var s = await r.json();
            el.textContent = s.running ? "\u{1F7E2} Running" : "\u{1F534} Stopped";  // textContent: never innerHTML
        } catch (e) {
            el.textContent = "\u26AA Unreachable";
        }
    }
    refresh();
    setInterval(refresh, 2000);
})();
