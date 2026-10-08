# Harvest

A marketplace for whole food from Irish farms and home producers, built with **Django**. Producers list
food and set click-and-collect slots. Buyers search, fill a basket, reserve a slot and pay when they
collect. What sets Harvest apart is its **ingredient analyser**: every product is checked for additives and
markers of ultra-processing, and shown with a NOVA group, a clean score and the reasons behind them. Staff
verify farms and moderate reported products in the admin.

**Stack:** Python 3.10+ · Django 5.2 LTS · Bootstrap 5 · SQLite · Pillow · python-decouple

Prices are in euro, times are Irish time (`Europe/Dublin`, clock changes included), and locations are the 26 counties.

## Features

- **Ingredient analyser** (see [How the analyser works](#how-the-analyser-works)):
  - It parses the label as written, including nested brackets, percentages and E-numbers in any form.
  - It matches each ingredient against a reference list of 330 additives and markers.
  - It assigns a **NOVA group 1–4**, a **clean score out of 100** with a grade from A to E, and plain-English
    reasons, such as "Contains E471 (mono- and diglycerides of fatty acids), an emulsifier: a marker of
    ultra-processing".
  - It warns sellers about allergens their ingredients mention but they haven't ticked.
- **Barcode pre-fill from Open Food Facts**: sellers of packaged food enter a barcode to fill in the name,
  ingredients and allergens.
  - Check digits are validated first.
  - Lookups are cached for 30 days, including "not found".
  - If the service is down, the seller just types the details.
  - Harvest's own analyser still decides, and the product page shows both verdicts side by side.
- **Two kinds of seller**:
  - **Home producers**: anyone can sell, with up to 8 live products.
  - **Verified farms**: they apply with a registration or herd number, and staff approve or reject them in
    the admin (the applicant gets an email either way). Verified farms get unlimited products, a "Verified
    farm" badge, a public page, a place in the farm directory, reviews, certified-organic labelling and
    veg-box subscriptions.
- **Search that matches anything**: one search box where every word must match something: product name,
  producer, county, category (with synonyms such as "veg" or "bread"), an ingredient, "organic" or
  "season". So `sourdough cork` and `organic eggs` both work.
  - **Filters:** category, county, maximum NOVA group, minimum clean score, **free from** (any of the
    14 EU allergens), organic, in season and verified farms only.
  - **Also:** price range, sorting, pagination and a JSON API at `/products/api/`.
  - An **In season** page lists what's at its best this month.
- **Products and photos**:
  - Draft → live → paused → archived, with units (per kg, per dozen, per jar…) and months in season.
  - Up to 6 photos each, re-encoded on upload, which **strips EXIF data such as GPS location**, with
    thumbnails.
- **Click and collect, pay at collection**:
  - **Collection points and slots:** producers add collection points (farm gate, market stall) with weekly
    collection times, for example "Saturdays 09:00–12:00, one-hour slots, 6 orders each". Slots are generated
    two weeks ahead.
  - **Basket:** buyers check out each producer's items separately.
  - **Reserve:** picking a slot holds the stock and the slot place for **15 minutes**. Two buyers can't
    both get the last jar.
  - **Confirm:** confirming copies the prices onto the order, so later price changes don't affect it.
- **Order lifecycle**: a state machine with timing rules and an audit trail (see
  [Order lifecycle](#order-lifecycle)).
  - **Expiry:** orders not accepted within 24 hours, or by the slot's start, cancel themselves.
  - **No-shows:** buyers who miss two collections in 90 days are limited to one open order at a time.
  - **Producer tools:** an order list and a printable **pick list** for each day.
- **Veg-box subscriptions** (verified farms):
  - **Joining:** buyers join a weekly or fortnightly box at a regular collection time, with a cap on
    subscribers.
  - **Generation:** a daily job creates each week's box orders. If the slot is full it uses the next slot
    that day. If there's no room at all, it records a missed delivery and tells both sides.
  - **Buyer controls:** skip a week (up to the cut-off), pause, resume or cancel.
- **Messaging**: one conversation per order between buyer and producer, with an unread badge and email
  notifications.
- **Reviews**: buyers who have collected an order from a verified farm can review it (1–5 stars) and update
  their review. The farm can reply once.
- **Saved food and searches**:
  - Save a product to get an email when its **price drops** or it's **back in stock**.
  - Save a search to get an email when a **new product matches** (at most daily per search).
- **Reports and moderation**: buyers report a product with a reason, and staff are emailed. In the admin,
  staff dismiss the report or unlist the product, which closes every open report on it and tells the
  producer.
- **Producer dashboard**: orders waiting, slot bookings for the next 7 days, low stock, and sales and best
  sellers over 30 days.
- **Email notifications** for orders, status changes, messages, alerts, subscriptions and farm decisions.
  In development they print to the console.

## How the analyser works

The engine is `apps/analysis/engine.py`: plain Python with no Django imports, so it can be tested on its own.

1. **Parse.** The label is split on commas and semicolons outside brackets (and on "and" between items,
   unless "and" is part of a known name like "mono- and diglycerides"). Bracketed groups become
   sub-ingredients. `emulsifier: soya lecithin` and `emulsifiers (E471, E472e)` record the function.
   Percentages are taken out, and `E 471`, `e-471` and `E–471` all become `E471`.
2. **Match.** Each leaf ingredient is matched by E-number, by name or alias, or by a known phrase inside it,
   against `apps/analysis/data/additives.json`. Staff can edit the list in the admin, and
   `reanalyse_products` reruns every product afterwards.
3. **Classify** using the [NOVA](https://en.wikipedia.org/wiki/Nova_classification) groups:

   | Group | When | Example |
   | --- | --- | --- |
   | 1 Unprocessed | Only whole foods | `oats`, `almonds, raisins`, carrots |
   | 2 Culinary ingredient | Only oils, butter, sugar, salt, vinegar… | `olive oil`, `butter, salt` |
   | 3 Processed | Whole foods with culinary ingredients or non-cosmetic additives (preservatives, acids) | `wheat flour, water, salt, yeast` |
   | 4 Ultra-processed | Any marker: emulsifiers, colours, sweeteners, flavourings, thickeners, modified starch, protein isolates, glucose-fructose syrup, hydrogenated fat… | `oat flour, glucose-fructose syrup, E471` |

4. **Score.** The score starts at 100:

   | Penalty | Points |
   | --- | --- |
   | First marker | −25 |
   | Each further marker | −10 |
   | Each other additive | −6 |
   | Sugar as the 1st or 2nd ingredient | −15 |
   | Sugar anywhere else | −5 |
   | Added salt | −3 |
   | Each ingredient beyond five | −2 |
   | Each unknown E-number | −5 |

   Grades: A ≥ 85, B ≥ 70, C ≥ 50, D ≥ 30, E below.

A worked example: a chocolate spread labelled *sugar, palm oil, hazelnuts (13%), skimmed milk powder,
fat-reduced cocoa, emulsifier: lecithins (soya), vanillin* scores **NOVA 4, 46/100, grade D**:

```
Contains E322 (lecithins), an emulsifier: a marker of ultra-processing
Contains vanillin, a flavouring: a marker of ultra-processing
Sugar is the 1st ingredient
Long ingredient list (7 ingredients)
```

Some deliberate choices: calcium carbonate and the vitamins in fortified flour, and the carbon dioxide in
sparkling water, are not treated as markers. Aliases of the same additive count once. "Lactose-free milk" is
not read as containing lactose.

## Order lifecycle

| From | Action | To | Who | Rule |
| --- | --- | --- | --- | --- |
| pending | accept | accepted | producer | before the slot starts |
| pending | reject | rejected | producer | a reason is required; stock is returned |
| pending | (automatic) | cancelled | system | after 24 h, or at the slot start if sooner; stock is returned |
| pending, accepted | cancel | cancelled | buyer | before the collection point's cut-off (12 h by default); stock is returned |
| accepted | mark ready | ready | producer | |
| ready | collect | collected | producer | records cash, card or other |
| ready | not collected | no show | producer | from 2 h after the slot ends; stock is not returned |

The API behind each page (`orders.services.allowed_actions`) decides which buttons each person sees, and
every request is checked again on the server. Each change is written to the order's history and emails the
other party.

## Architecture

```
.
├── apps/                 One Django app per feature, imported as apps.<name>
│   ├── core/             Base template, € / ★ / NOVA template filters, Bootstrap form mixin, email helper,
│   │                     counties / allergens / months, error pages, /health/, shared test factories
│   ├── accounts/         Sign up, log in/out, profile, password
│   ├── analysis/         Ingredient analyser engine, Additive reference list (330 entries),
│   │                     Open Food Facts client with BarcodeLookup cache, load_additives command
│   ├── producers/        Producer profiles, farm applications, collection points, slot rules and slots,
│   │                     reviews, farm directory and pages, generate_slots command
│   ├── catalogue/        Products, photos, selling, search and filters, JSON API, in-season page,
│   │                     reanalyse_products command
│   ├── orders/           Basket, stock holds, checkout, the order state machine, pick lists, dashboard,
│   │                     expire_pending_orders and release_expired_holds commands
│   ├── subscriptions/    Veg-box subscriptions, skips, missed deliveries, generate_box_orders command
│   ├── messaging/        One conversation per order, unread badge
│   ├── saved/            Favourites with price-drop and back-in-stock emails, saved searches
│   ├── reports/          Product reports and the moderation actions
│   └── demo/             seed_demo_data command
├── config/               Settings, URLs, WSGI/ASGI
├── manage.py
└── requirements.txt
```

Each app keeps its rules in `services.py`. Other apps call those functions rather than changing another
app's rows. Apps announce events with signals (`product_published`, `product_price_dropped`,
`order_status_changed`, …), and emails are sent by each app's `receivers.py`, so for example the catalogue
never imports the app that sends price-drop alerts. Where a lower app needs an answer from a higher one,
the higher app registers a callback at start-up. For example, orders tells catalogue how much stock is
held, and tells producers whether a collection point is still in use.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set SECRET_KEY
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver 8020
```

Open <http://127.0.0.1:8020/>. `seed_demo_data` creates:
- six verified farms and three home producers across Ireland;
- 44 products covering NOVA 1–4;
- orders in every state, reviews, messages, a subscription and a report.

It prints fresh passwords for every demo account, including `harvest_admin` for the admin site.
`seed_demo_data --reset` rebuilds the demo data.

### Scheduled jobs

In production, run these with cron or a scheduler:

| Command | When | What it does |
| --- | --- | --- |
| `generate_slots` | daily | Keeps collection slots 14 days ahead |
| `generate_box_orders` | daily | Creates veg-box orders for the coming week |
| `expire_pending_orders` | hourly | Cancels orders producers didn't accept in time |
| `release_expired_holds` | hourly | Clears old checkout holds (expired holds are already ignored) |
| `reanalyse_products` | after editing additives | Reruns the analyser on every product |

## Tests

```bash
python manage.py test
```

290 tests. They cover:
- **The analyser:** a table of real labels, parsing edge cases, score arithmetic, reasons and allergen hints.
- **The Open Food Facts client:** with the network mocked.
- **Slot generation:** including the October clock change.
- **Stock and checkout:** holds with two buyers competing for the last item, slot capacity, expired holds,
  and prices locked at order time.
- **The order lifecycle:** every transition, with its timing and permission rules.
- **The no-show policy, subscriptions, messaging, reviews, alerts, reports, the dashboard and the demo data.**
- **The views:** login is required, and other people's orders, products and subscriptions return 404.

## Limitations

- Payment happens in person; there is no online payment.
- One currency and country (euro, Ireland).
- Emails print to the console unless an SMTP backend is configured in `.env`.
- The NOVA group is worked out from the label text. It is a guide, not a lab test, and it can only be as good
  as the ingredient list the seller enters.
