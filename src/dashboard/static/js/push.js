// "Enable push on this device" on the Alerts page.
// Needs HTTPS (or localhost), a service worker, and the browser's permission.
(function () {
    var button = document.getElementById("enable-push");
    var status = document.getElementById("push-status");
    if (!button) { return; }

    function say(text, ok) {
        status.textContent = text;
        status.className = "hint " + (ok === true ? "ok" : ok === false ? "bad" : "");
    }

    function urlBase64ToUint8Array(base64) {
        var padding = "=".repeat((4 - base64.length % 4) % 4);
        var raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
        var bytes = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) { bytes[i] = raw.charCodeAt(i); }
        return bytes;
    }

    function csrf() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : "";
    }

    button.addEventListener("click", function () {
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
            say("This browser can't receive push. On an iPhone, add Sentinel to the Home Screen first, then open it from there.", false);
            return;
        }
        if (!window.isSecureContext) {
            say("Push needs HTTPS. Open Sentinel through its https:// address.", false);
            return;
        }

        button.disabled = true;
        say("Asking for permission…");

        Notification.requestPermission().then(function (permission) {
            if (permission !== "granted") {
                throw new Error("Notifications were not allowed. Allow them in the browser settings and try again.");
            }
            return navigator.serviceWorker.register("/sw.js");
        }).then(function (registration) {
            return navigator.serviceWorker.ready.then(function () { return registration; });
        }).then(function (registration) {
            return fetch("/api/push/public-key").then(function (r) { return r.json(); })
                .then(function (data) {
                    return registration.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: urlBase64ToUint8Array(data.publicKey)
                    });
                });
        }).then(function (subscription) {
            return fetch("/api/push/subscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
                body: JSON.stringify(subscription.toJSON())
            }).then(function (r) {
                if (!r.ok) { throw new Error("The server did not accept this device."); }
                say("✅ This device will now get phone alerts.", true);
            });
        }).catch(function (error) {
            say(error.message || "Could not enable push on this device.", false);
        }).then(function () {
            button.disabled = false;
        });
    });
})();
