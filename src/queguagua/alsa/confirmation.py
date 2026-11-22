"""Read the outcome of a purchase from the page ALSA renders after it (step 4, "thank you").

The purchase app's summary component reads `success.ticketLocator` and offers the ticket PDF at
`getTicketPDFResourceURL&locator=<locator>` and wallet passes at `getWalletResourceURL&walletIndex=<i>`.
"""

import re
from typing import Any

from . import cachefile, config, pageparams
from .client import AlsaClient
from .errors import PaymentError

_LOCATOR = re.compile(r"\b([0-9][a-z0-9]{6})\b")


def _walk(o: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys and v:
                return v
            found = _walk(v, keys)
            if found:
                return found
    elif isinstance(o, list):
        for v in o:
            found = _walk(v, keys)
            if found:
                return found
    return None


def find_locator(purchase: dict) -> str | None:
    found = _walk(purchase, ("ticketLocator", "locator", "localizador", "purchaseLocator"))
    return found if isinstance(found, str) else None


def parse_result(client: AlsaClient, html: str, url: str | None = None) -> dict:
    params = pageparams.parse(html)
    pur = params.get("purchase", {})
    err = params.get("", {}).get("errorMessageKey") or pur.get("errorMessageKey")
    if (url and "RuntimeErrorRender" in url) or err:
        raise PaymentError("ALSA shows an error page instead of a confirmation", alsa_message=str(err) if err else None)
    locator = find_locator(pur)
    pdf_url = pur.get("getTicketPDFResourceURL")
    wallets = pur.get("jsonWalletList") if isinstance(pur.get("jsonWalletList"), list) else []
    out: dict[str, Any] = {"status": "confirmed" if locator else "unconfirmed", "locator": locator}
    if pdf_url and locator:
        out["ticket_pdf_url"] = f"{pdf_url}&locator={locator}"
    if wallets:
        out["wallet_passes"] = [{"index": i, "from": w.get("nombreOrigen"), "to": w.get("nombreDestino"),
                                 "seat": w.get("asiento")} for i, w in enumerate(wallets)]
    if not locator:
        # Keep the page (locally, 0600) so the shape can be fixed; it may hold personal data, so never print it.
        path = config.cache_dir() / "last-confirmation.html"
        cachefile.write_atomic(path, html)
        out["notice"] = ("ALSA answered, but the CLI couldn't read a locator from the page. Check your email or "
                         "`alsa tickets` before trying again.")
        out["saved_page"] = str(path)
    return out


def download_pdf(client: AlsaClient, url: str, dest) -> int:
    r = client.send("GET", url, what="ticket PDF", headers={"Accept": "application/pdf,*/*"})
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise PaymentError("ALSA didn't return the ticket PDF", status=r.status_code)
    cachefile.write_atomic(dest, r.content)
    return len(r.content)
