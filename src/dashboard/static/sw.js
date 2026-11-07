// Sentinel service worker: shows push alerts. It does not cache pages, so the
// app always shows live data.
self.addEventListener("install", function (event) {
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
    var data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }

    var title = data.title || "Sentinel alert";
    var options = {
        body: data.body || "Something happened at one of your cameras.",
        icon: "/static/icons/icon-192.png",
        badge: "/static/icons/icon-192.png",
        tag: "sentinel-alert",
        renotify: true,
        data: { url: data.url || "/notifications" }
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    var target = (event.notification.data && event.notification.data.url) || "/notifications";
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clients) {
            for (var i = 0; i < clients.length; i++) {
                if (clients[i].url.indexOf(target) !== -1 && "focus" in clients[i]) {
                    return clients[i].focus();
                }
            }
            return self.clients.openWindow(target);
        })
    );
});
