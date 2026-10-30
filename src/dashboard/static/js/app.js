(function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    var csrf = meta ? meta.content : "";

    // Live engine status on the dashboard.
    var statusEl = document.getElementById("engine-status");
    if (statusEl) {
        var refresh = function () {
            fetch("/api/status", { headers: { Accept: "application/json" } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (s) {
                    if (s) { statusEl.textContent = s.running ? "🟢 Running" : "🔴 Stopped"; }
                })
                .catch(function () { statusEl.textContent = "⚠️ Cannot reach server"; });
        };
        setInterval(refresh, 3000);
    }

    // "Test connection" on the Add Camera form.
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
