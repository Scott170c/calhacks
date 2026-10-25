#!/usr/bin/env python3
"""Phone screens for "Get the app": ONE page list -> images + the screen gallery in index.html.

SWAP POINT: edit PAGES below, then run
    python3 tools/make-screens.py
It (1) writes media/screens/android-<id>.webp (+ -dark.webp when a dark render is given),
(2) rewrites the Android gallery in index.html between the <!-- GALLERY --> markers,
(3) deletes stale .webp files in media/screens.
Order of PAGES = order of the screens (left to right, then row by row). Wide screens show one row of
up to 6; more pages wrap into balanced rows (10 pages -> 5 + 5). Give dark renders for every page or
for none, so the gallery never mixes light and dark screens.
iPhone: the app is paused and not downloadable, so the site shows no iPhone screens (only a
"coming soon" note). When a real iPhone build exists, add an "ios" render per page and a second gallery.
Needs Pillow. Not deployed (hidden by _redirects, not in the deploy ZIP).
"""
import json, os, re
from PIL import Image

A2 = "/cloudspace/smartbag/android-ui/3.2/"   # Android 3.2 renders (Robolectric, 411 dp): accounts, pairing, trips, wallet
A3 = "/cloudspace/smartbag/android-ui/3.3/"   # Android 3.3: account with notification settings
A4 = "/cloudspace/smartbag/android-ui/3.4/"   # Android 3.4/3.5: shopping with budget, fix an item, budget, receipt summary
                                              # (3.5 changed no screens; its changes are Bluetooth session handling)
def r(base, name):
    """(light, dark) pair for one render."""
    return (base + "411-light/" + name + ".png", base + "411-dark/" + name + ".png")

PAGES = [
    # id, label (caption under the screen), alt (the page adds "Bag It on Android."), android: (light, dark or None)
    dict(id="welcome", label="Welcome",
         alt="Welcome screen: The bag that checks you out, three steps (drop it in, it knows, walk out), and buttons to create an account or log in.",
         android=r(A2, "20-welcome")),
    dict(id="create-account", label="Create account",
         alt="Create account: name, email and password; your cards and bags stay with your account on any phone.",
         android=r(A2, "21-create-account")),
    dict(id="pair", label="Pair your bag",
         alt="Pair your bag: bags nearby, with the one right next to the phone at the top, and a demo bag option.",
         android=r(A2, "25-pair-scan")),
    dict(id="shopping", label="Shopping",
         alt="Shopping at Bayside Grocer: each item with its price, one item the store doesn’t sell marked won’t be charged, a suggestion, and Just walk out with $8.26 and $11.74 left of a $20.00 budget.",
         android=r(A4, "52-cart-budget-recs")),
    dict(id="fix-item", label="Fix an item",
         alt="Change item: pick what you actually put in, from the store’s products with their prices.",
         android=r(A4, "55-change-item")),
    dict(id="budget", label="Budget",
         alt="Budget: set a budget per trip; the app shows what’s left as you shop and keeps it for your next trips.",
         android=r(A4, "56-budget-sheet")),
    dict(id="receipt", label="Receipt",
         alt="Receipt: Paid as you left Bayside Grocer, $17.16 with a demo card, an exit code to show staff if asked, and the items.",
         android=r(A4, "57-receipt-summary")),
    dict(id="trips", label="Trips",
         alt="Trips: past trips by day with store, time, number of items and total.",
         android=r(A2, "38-trips")),
    dict(id="wallet", label="Wallet",
         alt="Wallet: the card that pays when you walk out, other saved cards, Add a card, and a note that payments are simulated.",
         android=r(A2, "40-wallet")),
    dict(id="account", label="Account",
         alt="Account: your name and email, your bags with Pair a bag, notification settings, app permissions and Sign out.",
         android=r(A3, "43-account")),
]
WIDTH = 560          # about 2x the largest display width (~250 px at 2 columns on a tablet)
HEIGHT = 1213        # display box ratio; renders are cropped/fit to WIDTH x HEIGHT
QUALITY = 80
# Android renders carry a placeholder status-bar clock in the top-left corner, which the phone frame's
# rounded corner cuts in half. Blank that strip (source pixels) to the background colour.
BLANK_TOP = {"android": 60, "ios": 0}

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "media", "screens")
os.makedirs(OUT, exist_ok=True)

def make(src, name, plat):
    im = Image.open(src).convert("RGB")
    if BLANK_TOP.get(plat):
        top = BLANK_TOP[plat]
        im.paste(im.getpixel((im.width // 2, top // 2)), (0, 0, im.width, top))
    h = round(im.height * WIDTH / im.width)
    im = im.resize((WIDTH, h), Image.LANCZOS)
    if h != HEIGHT:   # pad/crop the bottom to the shared box (renders differ by ~1 px)
        box = Image.new("RGB", (WIDTH, HEIGHT), im.getpixel((WIDTH // 2, h - 1)))
        box.paste(im.crop((0, 0, WIDTH, min(h, HEIGHT))), (0, 0))
        im = box
    path = os.path.join(OUT, name)
    im.save(path, "WEBP", quality=QUALITY, method=6)
    print(f"{name:32s} {os.path.getsize(path) // 1024:3d} KB  <- {src}")
    return "media/screens/" + name

made, data = set(), []
for p in PAGES:
    row = dict(id=p["id"], label=p["label"], alt=p["alt"])
    for plat in ("android",):
        light, dark = p[plat]
        row[plat] = make(light, f"{plat}-{p['id']}.webp", plat)
        row[plat + "Dark"] = make(dark, f"{plat}-{p['id']}-dark.webp", plat) if dark else None
        made.update(x.split("/")[-1] for x in (row[plat], row[plat + "Dark"]) if x)
    data.append(row)
for f in os.listdir(OUT):
    if f.endswith(".webp") and f not in made:
        os.remove(os.path.join(OUT, f)); print("removed stale", f)

idx = os.path.join(ROOT, "index.html")
html = open(idx, encoding="utf-8").read()
n = len(data)
rows = -(-n // 6)
cols = -(-n // rows)          # balanced columns for wide screens, at most 6
NAME = {"android": ("Android", "Android app", "Screens show demo data.")}
def gallery(plat):
    name, head, note = NAME[plat]
    items = []
    for i, r in enumerate(data):
        eager = plat == "android" and i < cols    # first row of the default gallery; everything else lazy
        src = (f'<source srcset="{r[plat + "Dark"]}" media="(prefers-color-scheme: dark)">' if r[plat + "Dark"] else "")
        img = (f'<img src="{r[plat]}" width="{WIDTH}" height="{HEIGHT}" decoding="async"'
               + ("" if eager else ' loading="lazy"') + f' alt="Bag It on {name}. {r["alt"]}">')
        items.append(f'<li><figure><div class="ph"><picture>{src}{img}</picture></div><figcaption>{r["label"]}</figcaption></figure></li>')
    return (f'<div class="gal" id="gal-{plat}"><div class="gal-h"><h3>{head}</h3><p>{note}</p></div>\n'
            f'<ul class="shots" style="--cols:{cols}" aria-label="{head} screens">\n' + "\n".join(items) + "\n</ul></div>")
block = ("<!-- GALLERY (generated by tools/make-screens.py; edit PAGES there) -->\n"
         + gallery("android") + "\n<!-- /GALLERY -->")
html, k = re.subn(r"<!-- GALLERY.*?<!-- /GALLERY -->", lambda m: block, html, flags=re.S)
if k != 1:
    raise SystemExit("index.html: <!-- GALLERY --> markers not found")
open(idx, "w", encoding="utf-8").write(html)
print(f"index.html: {n} pages, {cols} per row on wide screens")
