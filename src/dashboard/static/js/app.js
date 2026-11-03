(function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var csrf = meta ? meta.content : "";

    // ---- Dashboard: engine status + live camera tiles ------------------
    var statusEl = document.getElementById("engine-status");

    function statusText(s) {
        if (s.loading) { return "⏳ Loading AI models…"; }
        if (s.running && s.error) { return "🟡 Running. " + s.error; }
        if (s.running) { return "🟢 Running"; }
        if (s.error) { return "🔴 Stopped. " + s.error; }
        return "🔴 Stopped";
    }

    function updateTiles(s) {
        var byId = {};
        (s.cameras || []).forEach(function (c) { byId[c.id] = c; });

        document.querySelectorAll("[data-camera-id]").forEach(function (tile) {
            var cam = byId[tile.getAttribute("data-camera-id")];
            var badge = tile.querySelector(".badge");
            var img = tile.querySelector("img");

            if (!cam) {
                badge.textContent = s.running ? "starting…" : "engine stopped";
                badge.className = "badge";
                if (img.getAttribute("src")) {
                    img.removeAttribute("src");
                    img.className = "live";
                }
                return;
            }

            badge.textContent = cam.error && cam.state !== "online"
                ? cam.state + ": " + cam.error
                : cam.state;
            badge.className = "badge " +
                (cam.state === "online" ? "ok" : cam.state === "reconnecting" ? "warn" : "");

            if (cam.state === "online" && !img.getAttribute("src")) {
                img.setAttribute("src", img.getAttribute("data-stream"));
                img.className = "live show";
            }
        });
    }

    if (statusEl) {
        var refresh = function () {
            fetch("/api/status", { headers: { Accept: "application/json" } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (s) {
                    if (!s) { return; }
                    statusEl.textContent = statusText(s);
                    updateTiles(s);
                })
                .catch(function () { statusEl.textContent = "⚠️ Cannot reach server"; });
        };
        refresh();
        setInterval(refresh, 3000);
    }

    // ---- Add Camera form: "Test connection" ------------------------------
    var testBtn = document.getElementById("test-camera");
    if (testBtn) {
        var form = document.getElementById("camera-form");
        var result = document.getElementById("test-result");
        var preview = document.getElementById("test-preview");

        testBtn.addEventListener("click", function () {
            result.className = "hint";
            result.textContent = "Connecting… this can take a few seconds.";
            preview.className = "preview";
            testBtn.disabled = true;

            fetch("/api/cameras/test", {
                method: "POST",
                headers: { "X-CSRF-Token": csrf },
                body: new FormData(form)
            })
                .then(function (r) {
                    var type = r.headers.get("Content-Type") || "";
                    if (r.ok && type.indexOf("image/") === 0) {
                        return r.blob().then(function (blob) {
                            preview.src = URL.createObjectURL(blob);
                            preview.className = "preview show";
                            result.className = "hint ok";
                            result.textContent = "✅ Connected. This is what the camera sees.";
                        });
                    }
                    return r.json().then(function (data) {
                        result.className = "hint bad";
                        result.textContent = data.error || "Could not connect.";
                    });
                })
                .catch(function () {
                    result.className = "hint bad";
                    result.textContent = "Could not reach the server.";
                })
                .then(function () { testBtn.disabled = false; });
        });
    }
})();
