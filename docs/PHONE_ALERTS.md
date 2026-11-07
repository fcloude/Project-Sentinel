# Phone alerts (Web Push)

Phone and browser alerts use the standard **Web Push** system. Browser vendors
(Google, Apple, Mozilla) run the delivery servers; Sentinel sends each message
encrypted, so the vendor can't read it.

## What you need
1. **HTTPS.** Push only works over `https://` or `http://localhost`. For a home
   setup, the easiest route is a private tunnel such as Tailscale Serve, or a
   reverse proxy with a certificate (Caddy handles this automatically).
2. **The package:** `python -m pip install pywebpush` (not yet verified here).
3. **iPhone:** iOS only allows push for apps added to the Home Screen. Open
   Sentinel in Safari, tap Share, then *Add to Home Screen*, open it from there,
   and press *Enable push on this device* on the Alerts page.
4. **Android / desktop:** open the HTTPS address in Chrome or Edge and press
   *Enable push on this device*.

## Testing status
- Verified in tests: key creation, subscription validation and storage, dead
  subscription clean-up, the service worker and manifest being served.
- **Not verified:** actual delivery to a real phone. Check it yourself:
  press Enable push, then Test on the Alerts page for the phone channel.
