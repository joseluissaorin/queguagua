"""`alsa` CLI. Prints JSON to stdout; errors go to stderr as {"error": {...}} with the exit codes
1 (internal), 2 (usage), 3 (auth), 4 (payment), 5 (blocked/upstream) and 7 (ALSA's site changed).
"""

import getpass
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, NoReturn, Optional

import typer

from . import account as account_mod, auth, config, package_version, secrets
from . import search as search_mod, stations as stations_mod
from .client import AlsaClient
from .errors import AlsaError, UsageError
from .output import render, render_error

app = typer.Typer(
    name="alsa",
    help="ALSA: stops, timetables and fares, seats and extras, the Abono Único, "
         "your Alsa Plus account, and checkout with your saved card, points or any ALSA payment method. "
         "Output is JSON.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,  # tracebacks would print locals (cookies, passwords)
)
bonos_app = typer.Typer(help="Bonos and passes: yours, the ones sold for a route, and buying one.",
                        no_args_is_help=True)
abono_app = typer.Typer(help="The Abono Único (state unlimited pass): status, check and buy.", no_args_is_help=True)
app.add_typer(bonos_app, name="bonos")
app.add_typer(abono_app, name="abono")


def make_client() -> AlsaClient:
    """The client every command uses (tests replace this)."""
    return AlsaClient()


@contextmanager
def _client() -> Iterator[AlsaClient]:
    client = make_client()
    try:
        with client:
            yield client
    except AlsaError as err:
        if client.retries and not err.retries:
            err.retries = list(client.retries)
        raise


def _fail(err: AlsaError) -> NoReturn:
    typer.echo(render_error(err), err=True)
    raise typer.Exit(err.exit_code)


def _emit(produce: Callable[[], Any]) -> None:
    try:
        payload = produce()
        text = render(payload)
    except (typer.Exit, typer.Abort):
        raise
    except AlsaError as err:
        _fail(err)
    except KeyboardInterrupt:
        _fail(AlsaError("interrupted"))
    except Exception as exc:  # never echo messages: they can embed URLs or cookies
        _fail(AlsaError(f"unexpected internal error: {type(exc).__name__}"))
    typer.echo(text)


def _version(value: bool) -> None:
    if value:
        typer.echo(package_version)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True,
                                          help="Print the version and exit.")] = False,
) -> None:
    pass


# ---- stops ---------------------------------------------------------------------------------------------


@app.command()
def stations(
    query: Annotated[Optional[str], typer.Argument(help="Name (accents and case ignored) or id.")] = None,
    limit: Annotated[int, typer.Option(help="At most this many matches.")] = 10,
    refresh: Annotated[bool, typer.Option(help="Ask ALSA for its current list instead of the shipped one.")] = False,
    reachable_from: Annotated[Optional[str], typer.Option("--from", help="Only places ALSA sells from this stop.")] = None,
) -> None:
    """Stops and city groups ("Madrid (Todas las paradas)") matching a name or id, best first."""

    def produce():
        if refresh or reachable_from:
            with _client() as client:
                pool = None
                if refresh:
                    pool = stations_mod.fetch_remote(client)
                if reachable_from:
                    origin = stations_mod.resolve(reachable_from, client)
                    pool = stations_mod.destinations(client, origin["id"])
                matches = stations_mod.search(query or "", pool, limit) if query else [
                    stations_mod.public({**s, "group": bool(s.get("stops"))}) for s in (pool or [])[:limit]]
        else:
            matches = stations_mod.search(query or "", limit=limit) if query else []
        out = {"query": query, "count": len(matches), "stations": matches}
        if query and not matches:
            out["suggestions"] = stations_mod.suggestions(query)
        return out

    _emit(produce)


# ---- search --------------------------------------------------------------------------------------------

DateOpt = Annotated[str, typer.Option("--date", "-d", help="YYYY-MM-DD, DD/MM/YYYY, today, tomorrow or a weekday (friday, viernes).")]


def _passengers(adults: int, young: int, seniors: int, children: int, babies: int) -> search_mod.Passengers:
    return search_mod.Passengers(adults=adults, young=young, seniors=seniors, children=children, babies=babies)


@app.command()
def search(
    origin: Annotated[str, typer.Argument(help="From: stop name or id.")],
    destination: Annotated[str, typer.Argument(help="To: stop name or id.")],
    date: DateOpt = "today",
    return_date: Annotated[Optional[str], typer.Option("--return", "-r", help="Return date (round trip).")] = None,
    open_return: Annotated[bool, typer.Option("--open-return", help="Open return (vuelta abierta).")] = False,
    adults: Annotated[int, typer.Option("--adults", "-a", help="Adults 26-59.")] = 1,
    young: Annotated[int, typer.Option("--young", help="Young 12-25.")] = 0,
    seniors: Annotated[int, typer.Option("--seniors", help="60 and over.")] = 0,
    children: Annotated[int, typer.Option("--children", help="Children 4-11.")] = 0,
    babies: Annotated[int, typer.Option("--babies", help="Babies 0-3 (no seat).")] = 0,
    promo: Annotated[Optional[str], typer.Option("--promo", help="Promo code or bono code.")] = None,
    abono: Annotated[bool, typer.Option("--abono", help="Use your Abono Único (from your account, or "
                                        "--abono-code + --document).")] = False,
    abono_code: Annotated[Optional[str], typer.Option("--abono-code", help="Abono Único security code.")] = None,
    document: Annotated[Optional[str], typer.Option("--document", help="Abono Único holder's DNI/NIE.")] = None,
    after: Annotated[Optional[str], typer.Option("--after", help="Leaving at or after HH:MM.")] = None,
    before: Annotated[Optional[str], typer.Option("--before", help="Leaving at or before HH:MM.")] = None,
    arrive_by: Annotated[Optional[str], typer.Option("--arrive-by", help="Arriving by HH:MM that day.")] = None,
    service: Annotated[Optional[str], typer.Option("--service", help="Comfort, Supra, Premium...")] = None,
    available: Annotated[bool, typer.Option("--available", help="Only journeys on sale.")] = False,
    direct: Annotated[bool, typer.Option("--direct", help="Only journeys without a change.")] = False,
    packages: Annotated[bool, typer.Option("--packages", help="Also price Básica/Flexible/Superflexible "
                                           "(one request per journey shown).")] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", help="At most this many journeys each way.")] = 20,
) -> None:
    """Journeys on a date with times, services, availability and every fare for your passengers."""

    def produce():
        with _client() as client:
            req = search_mod.SearchRequest(
                origin=stations_mod.resolve(origin, client), destination=stations_mod.resolve(destination, client),
                departure=config.parse_date(date),
                return_date=config.parse_date(return_date) if return_date else None,
                open_return=open_return,
                passengers=_passengers(adults, young, seniors, children, babies),
                promo_code=promo or "")
            if open_return and return_date:
                raise UsageError("use either --return DATE or --open-return")
            ab = None
            if abono or abono_code:
                ab = {"security_code": abono_code, "document": document}
            f = search_mod.Filters(after=after, before=before, arrive_by=arrive_by, service=service,
                                   available_only=available, direct_only=direct, limit=limit)
            return search_mod.run(client, req, f, packages=packages, abono=ab)

    _emit(produce)


@app.command()
def itinerary(
    origin: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Argument()],
    date: DateOpt = "today",
    departure: Annotated[str, typer.Option("--departure", "-t", help="The journey's departure time, HH:MM.")] = ...,
) -> None:
    """Every stop of one journey, with its times."""

    def produce():
        with _client() as client:
            req = search_mod.SearchRequest(origin=stations_mod.resolve(origin, client),
                                           destination=stations_mod.resolve(destination, client),
                                           departure=config.parse_date(date))
            search_mod.start(client, req)
            jl = search_mod.journey_list(client, "I")
            js = [search_mod.normalize_journey(j, "I") for j in jl["journeys"]]
            match = [j for j in js if (j["departure"] or "")[11:16] == departure]
            if not match:
                raise UsageError(f"no journey leaves at {departure}",
                                 details={"departures": [(j["departure"] or "")[11:16] for j in js]})
            j = match[0]
            return {"journey": j, "stops": search_mod.itinerary(client, j["index"], "I")}

    _emit(produce)


# ---- account -------------------------------------------------------------------------------------------


@app.command()
def login(
    user: Annotated[Optional[str], typer.Option("--user", "-u", help="Email or DNI. Default: the stored one.")] = None,
    password_stdin: Annotated[bool, typer.Option("--password-stdin", help="Read the password from stdin.")] = False,
    save: Annotated[bool, typer.Option("--save/--no-save", help="Store user and password in the macOS keychain "
                                       "(service queguagua-alsa).")] = False,
    code: Annotated[Optional[str], typer.Option("--code", help="Finish a login waiting for ALSA's emailed/SMS code.")] = None,
) -> None:
    """Sign in to Alsa Plus. Without flags it uses ALSA_USER/ALSA_PASSWORD or the keychain item `queguagua-alsa`."""

    def produce():
        with _client() as client:
            if code:
                res = auth.submit_code(client, code)
            else:
                u, pw, source = secrets.credentials(user)
                if password_stdin:
                    pw = sys.stdin.readline().rstrip("\n")
                    source = "stdin"
                if not u:
                    if not sys.stdin.isatty():
                        raise UsageError("no stored user: pass --user")
                    u = input("Alsa Plus email or DNI: ").strip()
                if not pw:
                    if not sys.stdin.isatty():
                        raise UsageError("no stored password: use --password-stdin or the keychain")
                    pw = getpass.getpass("Alsa Plus password: ")
                    source = "prompt"
                res = auth.login(client, u, pw)
                if res["status"] == "logged_in" and save and source in ("prompt", "stdin", "env"):
                    res["saved_to_keychain"] = secrets.save_to_keychain(u, pw)
                res["credentials_from"] = source
            if res["status"] == "logged_in":
                res["account"] = account_mod.whoami(client)
            return res

    _emit(produce)


@app.command()
def logout(
    forget: Annotated[bool, typer.Option("--forget", help="Also delete the password from the keychain.")] = False,
) -> None:
    """Drop the Alsa Plus session kept by the CLI."""

    def produce():
        with _client() as client:
            res = auth.logout(client)
            if forget:
                acct = secrets.keychain_account()
                res["keychain_deleted"] = bool(acct and secrets.delete_from_keychain(acct))
            return res

    _emit(produce)


@app.command()
def whoami(
    relogin: Annotated[bool, typer.Option("--relogin/--no-relogin", help="Sign in again with the stored "
                                          "credentials if the session expired.")] = True,
) -> None:
    """Your Alsa Plus account: level, points and their value, purse."""

    def produce():
        with _client() as client:
            if relogin:
                auth.ensure_login(client, required=False)
            return account_mod.whoami(client)

    _emit(produce)


@bonos_app.command("mine")
def bonos_mine(
    reveal: Annotated[bool, typer.Option("--reveal", help="Also print Abono Único security codes.")] = False,
) -> None:
    """Your bonos and passes (Mis bonos y tarjetas), with validity and the trips taken with each."""

    def produce():
        with _client() as client:
            items = account_mod.my_bonos(client, reveal=reveal)
            return {"count": len(items), "bonos": items}

    _emit(produce)


@abono_app.command("status")
def abono_status(
    reveal: Annotated[bool, typer.Option("--reveal", help="Also print the security code.")] = False,
) -> None:
    """Your Abono Único: validity, days left and trips taken with it (needs `alsa login`)."""

    def produce():
        from datetime import date as _date

        with _client() as client:
            items = [b for b in account_mod.my_bonos(client, reveal=reveal) if b["abono_unico"]]
            for b in items:
                if b["valid_to"]:
                    b["days_left"] = max(0, (_date.fromisoformat(b["valid_to"]) - config.today()).days + 1)
            current = [b for b in items if b["valid_today"]]
            return {"has_valid_abono": bool(current), "count": len(items), "abonos": items}

    _emit(produce)


@abono_app.command("check")
def abono_check(
    date: DateOpt = "today",
    abono_code: Annotated[Optional[str], typer.Option("--abono-code", help="Security code (default: from your account).")] = None,
    document: Annotated[Optional[str], typer.Option("--document", help="Holder's DNI/NIE.")] = None,
) -> None:
    """Check that ALSA accepts an Abono Único for a travel date (nothing is booked)."""

    def produce():
        with _client() as client:
            d = config.parse_date(date)
            code, doc, dtype, src = abono_code, document, 1, "flags"
            if not code:
                ab = account_mod.abono_for(client, d)
                code, doc, dtype, src = ab["security_code"], ab["document"], ab["document_type"], "account"
            if not doc:
                raise UsageError("pass --document with --abono-code")
            abono_id = search_mod.check_unified_ticket(client, security_code=code, document=doc,
                                                       document_type=dtype, departure=d)
            return {"valid": True, "date": d.isoformat(), "abono_id": abono_id, "source": src}

    _emit(produce)


# ---- booking -------------------------------------------------------------------------------------------

Origin = Annotated[str, typer.Argument(help="From: stop name or id.")]
Dest = Annotated[str, typer.Argument(help="To: stop name or id.")]
DepartureOpt = Annotated[Optional[str], typer.Option("--departure", "-t", help="Outward departure time HH:MM.")]
JourneyOpt = Annotated[Optional[int], typer.Option("--journey", help="Outward journey index from `search`.")]
ToStopOpt = Annotated[Optional[str], typer.Option("--to-stop", help="Pick among same-time journeys by arrival stop.")]
FromStopOpt = Annotated[Optional[str], typer.Option("--from-stop", help="... or by departure stop.")]
ServiceOpt = Annotated[Optional[str], typer.Option("--service", help="... or by service (Comfort, Supra...).")]
PackageOpt = Annotated[Optional[str], typer.Option("--package", help="basica, flexible or superflexible "
                                                   "(default: the cheapest).")]
ReturnOpt = Annotated[Optional[str], typer.Option("--return", "-r", help="Return date (round trip).")]
RetDepOpt = Annotated[Optional[str], typer.Option("--return-departure", help="Return departure time HH:MM.")]
SeatOpt = Annotated[Optional[list[int]], typer.Option("--seat", help="Seat number, once per passenger in order.")]
RetSeatOpt = Annotated[Optional[list[int]], typer.Option("--return-seat", help="Return seat, once per passenger.")]
SeatPrefOpt = Annotated[Optional[str], typer.Option("--seat-pref", help="window, aisle or any: choose the "
                                                    "cheapest such seat for everyone (seat choice may cost extra).")]
ExtraOpt = Annotated[Optional[list[str]], typer.Option("--extra", help="pet, sport, insurance, block-seat, carbon, "
                                                       "assistance, or an ALSA service id. Repeatable.")]
PaxOpt = Annotated[Optional[list[str]], typer.Option("--passenger", "-p", help="'Nombre;Apellidos;DNI"
                                                     "[;nie|passport|other][;discount]', once per passenger. "
                                                     "Default for the first: your Alsa Plus account.")]
DiscOpt = Annotated[Optional[list[str]], typer.Option("--discount", help="familia-general, familia-especial or "
                                                      "discapacidad; prefix 'N:' for passenger N (default 1).")]
PayOpt = Annotated[str, typer.Option("--pay", help="saved-card (default), card, points, points+saved-card, "
                                     "points+card, purse, paypal, bizum, google-pay, klarna, free.")]


def _buy_options(**kw) -> "purchase_mod.BuyOptions":
    from . import purchase as purchase_mod

    return purchase_mod.BuyOptions(
        departure=kw["departure"], journey=kw["journey"], to_stop=kw["to_stop"], from_stop=kw["from_stop"],
        service=kw["service"], package=kw["package"], return_departure=kw.get("return_departure"),
        return_package=kw.get("return_package"), seats=kw.get("seat") or [], return_seats=kw.get("return_seat") or [],
        seat_pref=kw.get("seat_pref"), extras=kw.get("extra") or [], passengers=kw.get("passenger") or [],
        discounts=kw.get("discount") or [], email=kw.get("email"), phone=kw.get("phone"), sms=kw.get("sms", False),
        pay=kw.get("pay") or "saved-card", save_card=kw.get("save_card", False), pay_later=kw.get("pay_later", False),
        abono=kw.get("abono", False), abono_code=kw.get("abono_code"), document=kw.get("document"),
        whatsapp=kw.get("whatsapp", False), donate=kw.get("donate", False), wheelchair=kw.get("wheelchair"),
        wheelchair_passengers=kw.get("wheelchair_passenger") or [], transfer_seat=kw.get("transfer_seat", False),
        companion=kw.get("companion", False), large_family_card=kw.get("large_family_card"),
        large_family_expiry=kw.get("large_family_expiry"))


def _request(client, origin, destination, date, return_date, adults, young, seniors, children, babies, promo,
             open_return=False):
    if open_return and return_date:
        raise UsageError("use either --return DATE or --open-return")
    return search_mod.SearchRequest(
        origin=stations_mod.resolve(origin, client), destination=stations_mod.resolve(destination, client),
        departure=config.parse_date(date), return_date=config.parse_date(return_date) if return_date else None,
        open_return=open_return, passengers=_passengers(adults, young, seniors, children, babies),
        promo_code=promo or "")


@app.command()
def seats(
    origin: Origin, destination: Dest, date: DateOpt = "today", departure: DepartureOpt = None,
    journey: JourneyOpt = None, to_stop: ToStopOpt = None, from_stop: FromStopOpt = None, service: ServiceOpt = None,
    package: PackageOpt = None, return_date: ReturnOpt = None, return_departure: RetDepOpt = None,
    adults: Annotated[int, typer.Option("--adults", "-a")] = 1,
    abono: Annotated[bool, typer.Option("--abono", help="Use your Abono Único.")] = False,
) -> None:
    """The seat map of a journey (free seats, window/aisle, deck, price) and the extras it offers. Books nothing."""

    def produce():
        from . import purchase as purchase_mod

        with _client() as client:
            req = _request(client, origin, destination, date, return_date, adults, 0, 0, 0, 0, None)
            opt = _buy_options(departure=departure, journey=journey, to_stop=to_stop, from_stop=from_stop,
                               service=service, package=package, return_departure=return_departure, abono=abono,
                               pay="card")
            ctx = purchase_mod.prepare(client, req, opt, stop_at="step2")
            co = ctx["checkout"]
            out = {"journey": co.outward, "package": co.package and co.package["name"],
                   "seat_map": co.seat_map("I"), "extras_offered": co.services(), "quote": co.quote()}
            if co.ret:
                out["return_journey"] = co.ret
                out["return_seat_map"] = co.seat_map("V")
            return out

    _emit(produce)


def _buy_command(confirm_default: bool):
    def command(
        origin: Origin, destination: Dest, date: DateOpt = "today", departure: DepartureOpt = None,
        journey: JourneyOpt = None, to_stop: ToStopOpt = None, from_stop: FromStopOpt = None,
        service: ServiceOpt = None, fare: Annotated[Optional[str], typer.Option("--fare", help="Fare name or index.")] = None,
        package: PackageOpt = None, return_date: ReturnOpt = None, return_departure: RetDepOpt = None,
        return_package: Annotated[Optional[str], typer.Option("--return-package")] = None,
        open_return: Annotated[bool, typer.Option("--open-return", help="Open return (vuelta abierta, 10 % off).")] = False,
        adults: Annotated[int, typer.Option("--adults", "-a")] = 1,
        young: Annotated[int, typer.Option("--young")] = 0,
        seniors: Annotated[int, typer.Option("--seniors")] = 0,
        children: Annotated[int, typer.Option("--children")] = 0,
        babies: Annotated[int, typer.Option("--babies")] = 0,
        seat: SeatOpt = None, return_seat: RetSeatOpt = None, seat_pref: SeatPrefOpt = None,
        extra: ExtraOpt = None, passenger: PaxOpt = None, discount: DiscOpt = None,
        email: Annotated[Optional[str], typer.Option("--email", help="Contact email (default: your account's).")] = None,
        phone: Annotated[Optional[str], typer.Option("--phone", help="Contact mobile, e.g. '+34 600000000'.")] = None,
        sms: Annotated[bool, typer.Option("--sms", help="Also send the locator by SMS (0.10 €).")] = False,
        whatsapp: Annotated[bool, typer.Option("--whatsapp", help="Also send it by WhatsApp, when ALSA offers it.")] = False,
        donate: Annotated[bool, typer.Option("--donate", help="ALSA's 1 € donation to a social project.")] = False,
        wheelchair: Annotated[Optional[str], typer.Option("--wheelchair", help="onboard (travel in your wheelchair) "
                                                          "or hold (wheelchair in the hold).")] = None,
        wheelchair_passenger: Annotated[Optional[list[int]], typer.Option("--wheelchair-passenger",
                                        help="Which passenger(s) use a wheelchair (1-based; default 1).")] = None,
        transfer_seat: Annotated[bool, typer.Option("--transfer-seat", help="With onboard: transfer to a seat.")] = False,
        companion: Annotated[bool, typer.Option("--companion", help="A companion helps with boarding (100 % off).")] = False,
        large_family_card: Annotated[Optional[str], typer.Option("--large-family-card", help="Large-family card "
                                     "number (default: your account's).")] = None,
        large_family_expiry: Annotated[Optional[str], typer.Option("--large-family-expiry", help="Its expiry, DD/MM/YYYY.")] = None,
        pay: PayOpt = "saved-card",
        save_card: Annotated[bool, typer.Option("--save-card", help="With --pay card: save it in your account.")] = False,
        pay_later: Annotated[bool, typer.Option("--pay-later", help="With --pay paypal: PayPal in 3 instalments.")] = False,
        promo: Annotated[Optional[str], typer.Option("--promo", help="Promo code or bono code.")] = None,
        abono: Annotated[bool, typer.Option("--abono", help="Use your Abono Único (from your account).")] = False,
        abono_code: Annotated[Optional[str], typer.Option("--abono-code")] = None,
        document: Annotated[Optional[str], typer.Option("--document", help="Abono Único holder's document.")] = None,
        yes: Annotated[bool, typer.Option("--yes", "-y", help="Really buy. Without it nothing is booked or charged.")] = False,
        browser: Annotated[str, typer.Option("--browser", help="Browser for Worldline's page: chrome (default), "
                                             "msedge or chromium.")] = "chrome",
    ) -> None:
        def produce():
            from . import purchase as purchase_mod

            with _client() as client:
                req = _request(client, origin, destination, date, return_date, adults, young, seniors, children,
                               babies, promo, open_return)
                opt = _buy_options(**dict(
                    whatsapp=whatsapp, donate=donate, wheelchair=wheelchair, wheelchair_passenger=wheelchair_passenger,
                    transfer_seat=transfer_seat, companion=companion, large_family_card=large_family_card,
                    large_family_expiry=large_family_expiry,
                    departure=departure, journey=journey, to_stop=to_stop, from_stop=from_stop, service=service,
                    package=package, return_departure=return_departure, return_package=return_package, seat=seat,
                    return_seat=return_seat, seat_pref=seat_pref, extra=extra, passenger=passenger,
                    discount=discount, email=email, phone=phone, sms=sms, pay=pay, save_card=save_card,
                    pay_later=pay_later, abono=abono, abono_code=abono_code, document=document))
                opt.fare = fare
                if pay.split("+")[0] not in ("saved-card", "card", "points", "purse", "paypal", "bizum",
                                              "google-pay", "apple-pay", "klarna", "free"):
                    raise UsageError(f"unknown payment method {pay!r}")
                if pay == "apple-pay":
                    raise UsageError("Apple Pay only works in Safari on ALSA's own page; the CLI can't hand its "
                                     "session to Safari. Use saved-card, card, google-pay, paypal or bizum.")
                return purchase_mod.buy(client, req, opt, confirm=(yes and confirm_default), browser=browser)

        _emit(produce)

    return command


app.command(name="buy", help="Book and pay a journey. Without --yes it only prints the full quote "
            "(nothing booked or charged). Default payment: your saved card.")(_buy_command(True))
app.command(name="quote", help="Everything `buy` would do, stopping before payment: price breakdown, seats, "
            "extras, discounts and payment methods (saved card, points...).")(_buy_command(False))


# ---- after buying --------------------------------------------------------------------------------------

DocOpt = Annotated[Optional[str], typer.Option("--document", help="Passenger's DNI/NIE/passport "
                                               "(default: your Alsa Plus account's).")]


@app.command()
def tickets(
    months: Annotated[int, typer.Option("--months", help="How far back.")] = 12,
    page: Annotated[int, typer.Option("--page", help="Page of results (10 per page).")] = 1,
) -> None:
    """Your trips in Alsa Plus (Puntos y viajes), newest first, plus the locators of upcoming ones."""

    def produce():
        with _client() as client:
            return account_mod.trips(client, months=months, page=page)

    _emit(produce)


@app.command()
def ticket(
    locator: Annotated[str, typer.Argument(help="Booking locator, e.g. 1abcdef.")],
    document: DocOpt = None,
    qr: Annotated[bool, typer.Option("--qr", help="Include the boarding QR text.")] = False,
    manage: Annotated[bool, typer.Option("--manage", help="Also say whether each ticket can be changed or "
                                         "cancelled now.")] = False,
) -> None:
    """A booking: legs, seat, platform, bus plate and its live status (from alsa.es/info)."""

    def produce():
        from . import manage as manage_mod

        with _client() as client:
            out = manage_mod.lookup(client, locator, document, qr=qr)
            if manage:
                out["manage"] = manage_mod.manage_view(client, locator, document)
            return out

    _emit(produce)


@app.command()
def cancel(
    locator: Annotated[str, typer.Argument(help="Booking locator.")],
    document: DocOpt = None,
    ticket_no: Annotated[int, typer.Option("--ticket", help="Which ticket of the booking (1 = first).")] = 1,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Really cancel. Without it you get the refund preview.")] = False,
) -> None:
    """Cancel a ticket. Without --yes it only shows ALSA's breakdown: fee, refund and points returned."""

    def produce():
        from . import manage as manage_mod

        with _client() as client:
            return manage_mod.cancel(client, locator, document, ticket=ticket_no, confirm=yes)

    _emit(produce)


@app.command()
def pdf(
    locator: Annotated[str, typer.Argument(help="Booking locator.")],
    document: DocOpt = None,
    out: Annotated[Optional[str], typer.Option("--out", "-o", help="Where to save it (default ./alsa-<locator>.pdf).")] = None,
) -> None:
    """Download the ticket PDF."""

    def produce():
        from pathlib import Path

        from . import manage as manage_mod

        with _client() as client:
            return manage_mod.download_pdf(client, locator, document, Path(out or f"alsa-{locator.lower()}.pdf"))

    _emit(produce)


@app.command()
def track(
    origin: Annotated[str, typer.Argument(help="From: stop name or id.")],
    destination: Annotated[str, typer.Argument(help="To: stop name or id.")],
    departure: Annotated[Optional[str], typer.Option("--departure", "-t", help="Track today's bus that left at HH:MM.")] = None,
) -> None:
    """Localiza tu bus: today's recent buses on a route and, with --departure, where that one is (if ALSA knows)."""

    def produce():
        from . import track as track_mod

        with _client() as client:
            o, d = stations_mod.resolve(origin, client), stations_mod.resolve(destination, client)
            return track_mod.find(client, o["id"], d["id"], departure)

    _emit(produce)


# ---- bonos ---------------------------------------------------------------------------------------------


@bonos_app.command("route")
def bonos_route(origin: Origin, destination: Dest) -> None:
    """Bonos ALSA sells for a route (Abono Único, Bono Comparte 10 viajes, monthly, regional...)."""

    def produce():
        from . import bonos as bonos_mod

        with _client() as client:
            o, d = stations_mod.resolve(origin, client), stations_mod.resolve(destination, client)
            items = bonos_mod.route_catalogue(client, o["id"], d["id"])
            return {"origin": {"id": o["id"], "name": o["name"]}, "destination": {"id": d["id"], "name": d["name"]},
                    "count": len(items), "bonos": bonos_mod.public(items)}

    _emit(produce)


def _holder(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    from .booking import PassengerInfo

    p = PassengerInfo.parse(text)
    return {"name": p.name, "surname": p.surname, "document": p.document, "document_type": p.document_type}


BonoPay = Annotated[str, typer.Option("--pay", help="saved-card (default), card, paypal, bizum, google-pay, klarna.")]


@bonos_app.command("buy")
def bonos_buy(
    origin: Origin, destination: Dest,
    bono: Annotated[str, typer.Option("--bono", help="Type id or name from `alsa bonos route`.")] = ...,
    start: Annotated[Optional[str], typer.Option("--start", help="Validity start date (if the bono has one).")] = None,
    holder: Annotated[Optional[str], typer.Option("--holder", help="'Nombre;Apellidos;DNI' (default: you).")] = None,
    ministry_code: Annotated[Optional[str], typer.Option("--ministry-code", help="AJ26-/AN26- code for young/child bonos.")] = None,
    discount: Annotated[Optional[str], typer.Option("--discount", help="familia-general or familia-especial.")] = None,
    pay: BonoPay = "saved-card",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Really buy. Without it you get the quote.")] = False,
) -> None:
    """Buy a route bono. Without --yes it only shows the price and payment options."""

    def produce():
        from . import bonos as bonos_mod

        with _client() as client:
            o, d = stations_mod.resolve(origin, client), stations_mod.resolve(destination, client)
            return bonos_mod.buy(client, kind=bono, origin=o, destination=d,
                                 start=config.parse_date(start) if start else None, holder=_holder(holder),
                                 ministry_code=ministry_code, discount=discount, pay=pay, confirm=yes)

    _emit(produce)


@abono_app.command("buy")
def abono_buy(
    kind: Annotated[str, typer.Argument(help="adult (60 €) or young (30 €, needs --ministry-code).")] = "adult",
    start: Annotated[Optional[str], typer.Option("--start", help="First day of the 30 days (default today).")] = None,
    holder: Annotated[Optional[str], typer.Option("--holder", help="'Nombre;Apellidos;DNI' (default: you).")] = None,
    ministry_code: Annotated[Optional[str], typer.Option("--ministry-code", help="AJ26-... code for the young abono.")] = None,
    discount: Annotated[Optional[str], typer.Option("--discount", help="familia-general or familia-especial.")] = None,
    pay: BonoPay = "saved-card",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Really buy. Without it you get the quote.")] = False,
) -> None:
    """Buy an Abono Único (30 days, unlimited Comfort trips on state lines). Without --yes: quote only."""

    def produce():
        from . import bonos as bonos_mod

        with _client() as client:
            return bonos_mod.buy(client, kind=kind, start=config.parse_date(start) if start else None,
                                 holder=_holder(holder), ministry_code=ministry_code, discount=discount, pay=pay,
                                 confirm=yes)

    _emit(produce)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
