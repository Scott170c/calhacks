# bagitwith.us

Static site for Bag It. No build step, no cookies, no analytics, no third-party requests, system fonts only.

```
index.html          the page (inline CSS + SVG, small script: video play/pause, Android download button)
media/screens/      Android app screens for the Get the app gallery (see Screenshots below)
media/steps/        demo step stills cut from the recorded trip
tools/              make-screens.py (screen gallery page list) and make-demo-steps.py (not deployed)
brand/              logo, mark, favicon, touch icon, OG image, brand.md
media/              product film + app demo recordings (see media/README.md)
downloads/          bag-it.apk (Android app; stable name, replace the file to update)
DESIGN-SYSTEM.md    design system and decisions
_headers            headers for Netlify (APK type and download, video caching)
_redirects          hides internal docs/tools on Netlify (forced 404s)
```

Deploy: Netlify from GitHub, branch `website` of Scott170c/calhacks, publish directory `website` (exact steps under **Deploy to Netlify + Porkbun DNS** below). Netlify serves MP4 with HTTP range requests.
The QR code encodes https://bagitwith.us/downloads/bag-it.apk. The name is stable, so ship new versions by replacing the file and the version line.

Content rules: only true statements. Payments are simulated during early access; product images are illustrative; no prices, dates, store partners, testimonials or ratings until they are real.

## Deploy to Netlify + Porkbun DNS

Only Scott can do these steps (his Netlify and Porkbun accounts). Nothing here needs a password shared with anyone.

**1. Create the site (Netlify, about 3 minutes)**
1. app.netlify.com → **Add new project** (or *Add new site*) → **Import an existing project** → **GitHub**. Authorize Netlify for `Scott170c/calhacks` if asked (choose "Only select repositories" → calhacks).
2. Pick the repo **Scott170c/calhacks**.
3. **Branch to deploy:** `website`. **Base directory:** leave empty. **Build command:** leave empty. **Publish directory:** `website`. (The repo's `netlify.toml` at the branch root sets the same values, so the form may already show them.)
4. **Deploy**. When it finishes, open the `https://<site>.netlify.app` address Netlify shows and check: the film plays, *Download for Android* downloads `bag-it.apk`, and `/README.md` gives the 404 page.
5. Optional: **Project configuration → General → Project details → Change project name** to something like `bagitwith-us`, so the address is `bagitwith-us.netlify.app`.

**2. Add the domain (Netlify)**
1. **Domain management → Add a domain** → `bagitwith.us` → **Verify** → **Add domain**. Netlify adds `www.bagitwith.us` too and makes `bagitwith.us` primary (www redirects to it).
2. When Netlify offers Netlify DNS, choose **external DNS** (keep DNS at Porkbun). Netlify then shows *Awaiting External DNS*; that is expected until step 3.

**3. Point the domain at Netlify (Porkbun)**
1. porkbun.com → **Domain Management** → `bagitwith.us` → **DNS**.
2. Delete Porkbun's default parking records first: the `ALIAS` record on the root (`pixie.porkbun.com`) and the `CNAME` for `*` (also `pixie.porkbun.com`). Also make sure **URL Forwarding** is off for the domain.
3. Add:

   | Type | Host | Answer | TTL |
   |---|---|---|---|
   | A | *(blank, the root `@`)* | `75.2.60.5` | 600 |
   | CNAME | `www` | `<site>.netlify.app` (your Netlify address, e.g. `bagitwith-us.netlify.app`) | 600 |

   Don't add an AAAA record.

**4. HTTPS (Netlify)**
- Back in **Domain management**, both domains turn green within minutes (Porkbun is fast; worst case a few hours). Under **HTTPS**, click **Verify DNS configuration** and Netlify issues a free Let's Encrypt certificate automatically (or click **Provision certificate**). Leave *Force HTTPS* on.
- Check `https://bagitwith.us`, `https://www.bagitwith.us` (redirects) and `https://bagitwith.us/downloads/bag-it.apk` (downloads; the QR code on the page encodes this address, so scan it with an Android phone).

**Updating the site later:** push to the `website` branch; Netlify redeploys on every push. Don't merge the branch for this; Netlify watches `website` directly.

## Media
- `media/bagit-concept*` (16:9, and 4:5 below 600 px): 35.8 s hero film v2 (3D turntable and inside view of the bag rendered in Blender, then the walk-out from two AI stills and the app's receipt). The inside hardware is illustrative; the page says "Product images and the bag’s inside are illustrative." Sources and notes: /workspace/smartbag/film/v2 (notes.md; mirror /cloudspace/smartbag/film/v2). The previous 13.25 s film (v1) is kept at /workspace/smartbag/film/v1-site-backup and /cloudspace/smartbag/film/v1-site-backup (same file names; copy back over media/ to restore).
- `media/bagit-live-trip*` (16:9 from a 1920×1080 recording, 720×1160 portrait): 14.7 s recording of one real trip (receipt FXEH7X, $11.77) on the live service from the shopper's phone; a browser page mirroring the app's screens drove it with simulated location and items; demo payment.
- Sources (stills, recording page, full 31 s film): /workspace/smartbag/film (mirrored to /cloudspace/smartbag/film).

## Deploy bundle
Publish only the files in the ZIP built from this folder: index.html, 404.html, _headers, _redirects, brand/{favicon.svg,favicon-32.png,apple-touch-icon.png,og-image.jpg,logo.svg,mark.svg}, media/* (including media/screens/*.webp), downloads/*.apk. `_redirects` hides the internal docs if the whole folder is deployed.

## Page structure
Everything is visible while scrolling top to bottom; nothing is paged, scroll-linked or collapsed: hero (product film) → How it works (3 beats) → Demo (5 trip steps side by side, then the recorded video) → Get the app (screen gallery + Android | iPhone selector + panel) → FAQ (questions and answers all open) → footer. The header is sticky with a solid background and hairline; anchored jumps land below it via `scroll-padding-top` on `html` (the only scroll offset).

## Demo steps
The step row in #demo shows five stills cut from the recorded trip (`media/steps/trip-*.webp`, phone screen only, 420 px wide, lazy-loaded). `tools/make-demo-steps.py` lists the frame times and the crop; labels and one-line descriptions are in index.html. If the recording changes, re-time `STEPS` and rerun.

## Screenshots (swap point)
"Get the app" shows every Android screen at once in one gallery (one row of up to 6 on wide screens, rows of 3 on tablets, 2 columns on phones; 10 screens = 5 + 5), followed by the Android download panel and a one-line iPhone note. Nothing is selected or paged.

- **One page list:** `PAGES` at the top of `tools/make-screens.py` (id, caption, alt text, light + dark render). Run `python3 tools/make-screens.py`. It writes `media/screens/android-<id>[-dark].webp` (560 px wide, 11-29 KB), regenerates the gallery in index.html between the `<!-- GALLERY -->` markers (first row eager, rest lazy, width/height set) and deletes stale files. Order of the list = order on the page.
- **Current list (10):** Welcome, Create account, Pair your bag (3.2 renders), Shopping with a budget, Fix an item, Budget, Receipt (3.4 renders; 3.5 changed no screens), Trips, Wallet (3.2), Account (3.3, with notification settings). Sources: `/cloudspace/smartbag/android-ui/<version>/411-light|411-dark`.
- **Dark mode:** every page has a dark render, so the gallery follows the visitor's theme. Give dark renders for every page or none.
- Android renders have a placeholder status-bar clock in the top-left corner; the tool blanks that strip (`BLANK_TOP`) because the frame's rounded corner would cut it.
- Left out on purpose: the hidden Hardware test screen, error/edge states, Log in (only an error render exists), the notifications screen (server push is off, so the page doesn't promise notifications yet).

## iPhone availability
The iPhone app is paused: there is no App Store or TestFlight build, so the page shows no iPhone screens. The `#get-iphone` panel says "The iPhone app isn’t available yet. It’s coming to the App Store." with no badge or link; iPhone visitors' hero button reads "Coming soon to iPhone" and jumps there. When a real build is live: add iPhone renders (a second gallery in make-screens.py), replace the `<p class="plain">` in `#get-iphone` with the App Store link, and update the hero fine print, the meta description, the "Get it on Android." heading and the FAQ "Which phones does it work with?".

## Accounts, Wallet, pairing, budget (live in the Android app)
The page describes them: setup line under Get the app, FAQ "Do I need an account?", "How do I connect my bag?", "What if the app gets an item wrong?" (change quantity / pick the product, Android 3.4+), "Can I set a budget?" (Android 3.4+), "Will I be charged?" (Wallet, simulated payments, only type/last four/expiry kept) and the location/privacy answer (trips and approximate location are public test data; email, password and saved cards private). Push notifications are still being built: don't mention receipt notifications until they ship.

## Android download
`downloads/bag-it.apk` is Android 3.5 (versionCode 8, minSdk 26 = Android 8.0, 7,437,659 bytes = 7.4 MB), a copy of `/cloudspace/smartbag/SmartBag-3.5.apk`.

**Swapping in a new APK (e.g. 3.6) is one file + one line:**
1. `cp /cloudspace/smartbag/SmartBag-3.6.apk website/downloads/bag-it.apk` (same name, so the QR code and links stay valid).
2. In index.html, edit the version line in the Android panel: `<p class="meta">Version 3.6 · Android 8.0 or newer · X.X MB</p>` (size = bytes / 1,000,000, one decimal; check minSdk with `aapt dump badging`).
3. Commit and push the `website` branch; Netlify redeploys. Update this paragraph.
