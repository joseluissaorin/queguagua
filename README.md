# queguagua

[queguagua.com](https://queguagua.com)

**¿Qué guagua cojo?** Spanish buses (guaguas) from the terminal, one company at a time. The first one is
ALSA: search buses, fares and seats, use your Abono Único, and buy with the card already saved in your Alsa
Plus account. Every command prints JSON, so scripts and AI agents can use it as easily as people.

> **Unofficial.** Not affiliated with, endorsed by or supported by ALSA. The CLI talks to www.alsa.es the
> same way its own pages do (Liferay portlet resources and actions). That interface is undocumented and
> can change without notice.

## Features

- **Stops**: ~5,800 places ship with the CLI, matched by name (accents and case ignored) or id. City groups
  such as `Madrid (Todas las paradas)` and single stops such as `Madrid Estación Sur` both work.
- **Journeys and fares** for any route and date: times with the stop's real UTC offset, duration, changes,
  service (Comfort, Supra, Premium...), availability, every fare for your passengers, and optionally the fare
  packages (Básica, Flexible, Superflexible) for each journey. Round trips and open returns.
- **All passenger types**: adults, young (12-25), seniors (60+), children (4-11), babies (no seat); per
  passenger discounts (large family general/special, disability >32 % or companion); promo codes and bono codes.
- **Abono Único**: the CLI reads it from your account (`--abono`), checks it for the travel date and books
  Comfort trips at 0 € (Supra pays the difference). `queguagua alsa abono status` shows its validity and the trips taken
  with it; `queguagua alsa abono buy` buys or renews it.
- **Seats and extras**: the seat map (free seats, window or aisle, deck, price), pick a seat per passenger or
  let the CLI pick the cheapest window/aisle one; pets, sport equipment, travel insurance, blocking the adjacent
  seat, boarding assistance, carbon offset.
- **Checkout with your Alsa Plus account**: your saved card (default), Alsa Plus points (alone or combined with
  money), purse, a new card (and save it), PayPal (also in 3 instalments), Bizum, Google Pay or Klarna. Without
  `--yes` nothing is booked or charged: you get ALSA's full price breakdown.
- **After buying**: your trips, a booking's live status (platform, bus plate, seat, boarding QR), the ticket
  PDF, and cancellation with ALSA's refund preview first.
- **Bonos**: the bonos ALSA sells for a route (Bono 10 viajes, monthly passes, regional bonos...), and buying one.
- **Localiza tu bus**: today's buses on a route and, when ALSA has GPS data, where one is.

## Install

You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```sh
uv tool install 'queguagua[checkout] @ git+https://github.com/joseluissaorin/queguagua'
queguagua --help        # or the short form: qg
```

The `checkout` extra (Playwright, driving your installed Google Chrome) is only needed when money goes
through a payment page: the 3-D Secure step of your saved card, or Worldline's page for a new card, PayPal,
Bizum, Google Pay and Klarna. Searching, quoting, the Abono Único, points, purse and everything else work
without it.

## Quick start

```sh
queguagua alsa stations granada                                   # find a stop or its id
queguagua alsa search Granada Madrid -d 2026-12-04 --after 07:00 --limit 3
queguagua alsa search Granada Madrid -d 2026-12-04 --abono        # with your Abono Único (needs `queguagua alsa login`)
queguagua alsa search Granada Madrid -d viernes --abono           # dates also take a weekday: the next one (friday, viernes)
queguagua alsa seats Granada Madrid -d 2026-12-04 -t 08:00        # seat map and extras, books nothing
queguagua alsa quote Granada Madrid -d 2026-12-04 -t 08:00 --package flexible --seat-pref window --extra insurance
queguagua alsa buy Granada Madrid -d 2026-12-04 -t 08:00 --abono --yes          # 0 € with the Abono Único
queguagua alsa buy Granada Madrid -d 2026-12-04 -t 09:00 --pay points+saved-card --yes
queguagua alsa tickets                                            # your trips
queguagua alsa ticket 1abcdef --qr                                # status, seat, platform, boarding QR
queguagua alsa cancel 1abcdef                                     # refund preview; add --yes to cancel
queguagua alsa abono status
```

## Signing in

Most of the account features (saved card, points, purse, Abono Único from the account, your trips) need an
Alsa Plus login. The CLI uses ALSA's own password login:

```sh
queguagua alsa login --user you@example.com --save    # asks for the password, stores it in the macOS keychain
queguagua alsa login                                   # later: uses the stored credentials
queguagua alsa whoami
```

Credentials come from `ALSA_USER`/`ALSA_PASSWORD`, then the macOS keychain item with service `queguagua-alsa`
(account = your email or DNI), then the terminal prompt. The password is never printed, cached or put on a
command line. The session cookies live in the cache folder (`~/.cache/queguagua/alsa/session.json`, mode 0600);
when ALSA drops the session, commands that need it sign in again with the stored credentials.

If ALSA asks for a verification code (two-factor login), `queguagua alsa login` says so and `queguagua alsa login --code NNNNNN`
finishes it. Google sign-in can't be done from a terminal: give your account a password on alsa.es
("Olvidé mi contraseña") and use that.

## Buying

`queguagua alsa buy` runs ALSA's checkout in one session, exactly as the website does: search, journey and fare, fare
package, seats and extras, passengers and discounts, contact, payment. Choose the journey by its departure
time (`--departure 08:00`, plus `--to-stop` or `--service` when two leave at the same time) or by its
`--journey` index from `search`.

- **Passengers**: the first one defaults to your Alsa Plus account. Add `--passenger 'Nombre;Apellidos;DNI'`
  once per passenger (`;nie`, `;passport` or `;other` for other documents). Contact email and mobile default
  to your account's.
- **Seats**: `--seat 39` once per passenger, `--return-seat` for the way back, or `--seat-pref window|aisle|any`.
  Choosing a seat can cost money depending on the package (shown in the quote).
- **Extras**: `--extra pet|sport|insurance|block-seat|carbon|assistance` (repeatable) for everyone, or
  `--extra 2:pet` for passenger 2 only. `--donate` adds ALSA's 1 € donation; `--sms`/`--whatsapp` also send the
  locator that way.
- **Wheelchair**: `--wheelchair onboard|hold`, `--wheelchair-passenger N`, `--transfer-seat`, `--companion`
  (the companion travels free). Only offered when the journey has wheelchair places (`wheelchair_places` in
  `search`).
- **Babies** take no document: `--passenger 'Nombre;Apellidos'`.
- **Discounts**: `--discount familia-general|familia-especial|discapacidad`, prefixed `2:` for passenger 2.
  Large-family discounts need the card number and expiry (`--large-family-card`, `--large-family-expiry`);
  for the account holder they come from the account.
- **Payment** (`--pay`): `saved-card` (default), `card` (`--save-card` to keep it), `points`, `points+saved-card`,
  `points+card`, `purse`, `paypal` (`--pay-later` for 3 instalments), `bizum`, `google-pay`, `klarna`. When
  nothing is left to pay (Abono Único, points or purse covering it all) ALSA confirms at once.

Without `--yes`, `buy` stops right before payment and prints `status: reviewed` with ALSA's full breakdown,
the payment methods offered (with your saved card's type and last four digits) and the discounts available.
With `--yes`:

- if nothing is left to pay, the CLI submits and prints `status: confirmed` with the **locator**, the seat, a
  link to the ticket PDF and the wallet passes;
- if money is due, ALSA answers with a page that sends your browser to the payment platform: for your saved
  card, ALSA charges it and the page goes to Mastercard/Visa 3-D Secure (which may pass on its own or ask
  your bank, in its app or with a code); for a new card, PayPal, Bizum... it goes to Worldline's hosted page.
  The CLI opens Google Chrome with its session and serves ALSA's payment form at the page's own address, so
  the browser submits it exactly as on alsa.es. It serves the form without the 58 scripts of the portal
  around it, any of which could stall the payment. If the page hasn't left for the payment platform after
  90 s, the CLI stops and says that the bank's check never started. When the platform returns to ALSA,
  the CLI reads the locator or ALSA's refusal («Transacción cancelada o rechazada») and closes the window.
  Card data never reaches the CLI.

ALSA keeps the search and the cart in the server session, so commands sharing it run one at a time: a second
`queguagua alsa` command waits (and says so) until the first one ends. To watch a route while buying, give
the watcher its own session with `XDG_CACHE_HOME`/`XDG_CONFIG_HOME` pointing elsewhere.

Apple Pay is only offered by ALSA in Safari on its own page, which can't take over the CLI's session, so it
isn't supported. Open returns (`--open-return`) are priced in `search`, but ALSA's own checkout currently drops
them at the extras step (its website doesn't offer them either); `buy` says so instead of selling a one-way.

### What has been checked against ALSA

| Flow | Checked live |
|---|---|
| Stops, search (one way, round trip, mixed passengers), packages, itinerary | yes |
| Quote: seats, extras for all or one passenger, donation, discounts (disability), points + card | yes |
| Login with password, account, points, purse, bonos, trip history | yes |
| Abono Único from the account: check, search at 0 €, **real booking and cancellation** | yes (20 Nov 2026) |
| Ticket lookup, PDF, cancellation preview and confirmation | yes |
| Hand-over to Worldline's page with the CLI's session, and back (cancelled there, no card entered) | yes |
| Points paying the whole fare (a Superflexible upgrade with the Abono Único, 1 €) | yes (22 Nov 2026) |
| Saved card: ALSA charges it and hands over to 3-D Secure | the hand-over, yes (22 Nov 2026); see below |
| A real card charge (saved or new card, PayPal, Bizum...) | not yet: nothing was paid |
| Buying a bono for real | not yet: quotes only |
| Live GPS in Localiza tu bus | ALSA returned no data on every bus tried |

The saved card failed twice for real on 22 Nov 2026, without a charge either time:
- the CLI opened the 3-D Secure address itself, query string included. ALSA's page submits it as a GET
  form, which drops the query, and the bank answered «Transacción cancelada o rechazada»;
- after that fix, the browser sat on a blank alsa.es page while the seat stayed held. The CLI waited with
  `time.sleep`, and sync Playwright only handles a page's events and routed requests inside its own calls.
  On top of that, ALSA's page only submits once its 58 scripts have loaded.

Since then the CLI serves only ALSA's form, waits through Playwright, and gives up after 90 s if the page
hasn't left for the bank. `tests/test_gateway_browser.py` replays both failures in a real Chrome. A real
charge hasn't been made since.

## After buying

| Command | What it does |
|---|---|
| `queguagua alsa tickets` | Your Alsa Plus trips (locator, route, date, fare, price, points), plus upcoming locators |
| `queguagua alsa ticket LOCATOR` | Legs, seat, platform, bus number and plate, live status (`at_platform`, `boarding`, `on_route`...); `--qr` adds the boarding QR text, `--manage` what can be changed or cancelled now |
| `queguagua alsa pdf LOCATOR` | Saves the ticket PDF |
| `queguagua alsa cancel LOCATOR` | ALSA's refund preview (ticket price, fee, refund, points returned); `--yes` cancels |

A booking is found by its locator and the passenger's document (your account's by default, or `--document`).
ALSA only lets a ticket be managed a few minutes after it's issued; the CLI says so when that's the reason.

## Bonos and the Abono Único

```sh
queguagua alsa bonos mine                          # your bonos and passes, validity, trips taken with each
queguagua alsa bonos route Granada Madrid          # what ALSA sells for that route
queguagua alsa bonos buy Granada Madrid --bono "10 viajes" --start 2026-12-01      # quote; --yes to buy
queguagua alsa abono status                        # your Abono Único: validity, days left
queguagua alsa abono check -d 2026-12-04           # does ALSA accept it for that date?
queguagua alsa abono buy adult --start 2026-12-15  # quote the next one; --yes to buy (young: --ministry-code AJ26-...)
```

The Abono Único (60 € adult, 30 € young) gives unlimited Comfort trips on state bus lines for 30 days. Each
trip is still a 0 € ticket you book with it (`--abono`). It can't be changed or cancelled once bought.

## Companies

`queguagua empresas` lists the companies and what the CLI can do with each. Each company is a command
group with its own subpackage (`src/queguagua/alsa/`), so adding Titsa, Global, Avanza or Monbus means adding a
sibling package, not touching ALSA's.

## Output and errors

stdout is one JSON document. Errors go to stderr as `{"error": {...}}`; when ALSA explains a refusal in its
own words, that text is in `alsa_message`.

| Code | Meaning |
|---|---|
| `0` | ok; check `notice` and `status` (`reviewed`, `confirmed`, `unconfirmed`) |
| `1` | internal error (only the exception type is shown) |
| `2` | usage: bad arguments, unknown stop, journey not on sale, a code ALSA rejected |
| `3` | auth: login needed or refused |
| `4` | payment: refused, cancelled, or the outcome is unknown (check your email before retrying) |
| `5` | blocked or upstream: 403/429, Imperva challenge, queue-it waiting room, 5xx, timeout |
| `7` | ALSA's website changed |

The CLI follows queue-it's immediate bounce when no queue is active, retries only one-off 5xx or dropped
connections on safe requests, and never retries a purchase, a cancellation or a login. It never tries to get
past a waiting room, a reCAPTCHA or a challenge page.

## Contributing

```sh
uv sync
uv run pytest            # offline: HTTP is mocked
```

The website (queguagua.com) lives in `web/`: one static page whose drawing is written point by point with a
hand-drawn pen engine and animated with CSS keyframes, all in ultramarine. `cd web && npx tsx build.ts` writes
`web/dist/`; `?quieto` in the URL shows the finished drawing without animation.

Never commit real passenger or booking data, captures (HAR files), tickets, cookies or passwords.

## License

MIT. The stop list in `src/queguagua/alsa/data/` comes from ALSA's website and isn't covered by the MIT license.
ALSA is a trademark of its owner; this project uses the name only to say which service it works with. The
hand font in `web/publico/fuentes/` is Nothing You Could Do (SIL Open Font License, see its `OFL.txt`).
