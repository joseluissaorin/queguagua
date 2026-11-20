"""A tiny fake of www.alsa.es for offline tests: route handlers by p_p_resource_id / action / path."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx

from queguagua.alsa.client import AlsaClient

HOME = """<html><script>Liferay.authToken = 'AbCd1234';
params.alsaplusAuth = {};
params.alsaplusAuth["loginPasswordResourceURL"] = 'https://www.alsa.es/home?p_p_id=login&p_p_lifecycle=2&p_p_resource_id=loginPasswordResource';
params.alsaplusAuth["jsonBusplusUser"] = '%s';
</script></html>"""


def journey(index=0, dep="27/11/2026 08:00", arr="27/11/2026 13:00", dep_ms=1795734000000 + 8 * 3600000,
            price=23.28, service="Comfort", sale="V", dest="Madrid Estación Sur"):
    return {
        "index": index, "departureDate": dep_ms, "arrivalDate": dep_ms + 5 * 3600000,
        "departureDataToFilter": dep, "arrivalDataToFilter": arr,
        "originName": "Granada Estación De Autobuses", "originId": "9084",
        "destinationName": dest, "destinationId": "155", "lineName": "",
        "serviceTypeList": ["N"], "serviceTypeDescList": [service], "transfersNumber": 0, "transfersTown": [],
        "totalNumberOfStops": "1", "canBeSold": sale, "serviceCodes": "3224", "companyService": "203",
        "fares": [{"index": 0, "price": price, "fareType": "BASE", "fareName": "SUPER FLEX",
                   "fareConditions": "Puedes anular y cambiar", "outwardReturnRequired": "N",
                   "promotionCodeList": [], "travellersData": [{"passengerType": "ADULT", "amount": 1, "price": price}]}],
        "busCharacteristic": {"characteristicList": [{"code": "12", "description": "Admite bono ministerio"}],
                              "isNightBus": False, "isNonStopBus": False, "isDoubleDeckerBus": True,
                              "isFreeVoucherApplyable": True},
        "petAvailability": "AVAILABLE", "sportAvailability": "NO_AVAILABLE", "handicappedAvailability": "NO_AVAILABLE",
        "contiguousPaxAvailability": "AVAILABLE",
    }


class FakeAlsa:
    def __init__(self, user=None):
        self.calls = []
        self.user = user
        self.journeys = [journey(0), journey(1, dep="27/11/2026 09:00", dep_ms=1795734000000 + 9 * 3600000,
                                              price=47.35, service="Supra")]
        self.queue_once = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        q = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        rid = q.get("p_p_resource_id")
        action = next((v for k, v in q.items() if k.endswith("javax.portlet.action")), None)
        self.calls.append((request.method, url.path, rid or action))
        if url.hostname and "queue-it" in url.hostname:
            return httpx.Response(302, headers={"location": "https://www.alsa.es/?queueittoken=x"})
        if self.queue_once and rid:
            self.queue_once = False
            return httpx.Response(302, headers={"location": "https://alsa.queue-it.net/?c=alsa&t=x"})
        if rid == "GetJourneyListResource":
            return httpx.Response(200, json={"journeys": self.journeys, "voucherList": [], "carbonFootprint": 11})
        if rid == "GetPackageFaresResource":
            return httpx.Response(200, json={"packageFareList": [
                {"farePackageId": "45", "packageName": "Básica", "totalPassengerPackagePrice": 0.0, "enabled": True},
                {"farePackageId": "1001", "packageName": "Flexible", "totalPassengerPackagePrice": 2.0, "enabled": True,
                 "recommended": True}]})
        if rid == "CheckPromocodeResourceCommand":
            body = json.loads(request.content)
            ok = body["promoCode"] == "GOOD"
            return httpx.Response(200, json={"promoCode": body["promoCode"], "valid": ok,
                                             "message": None if ok else "Código promocional inexistente. Compruébalo."})
        if rid == "loginPasswordResource":
            body = json.loads(request.content)
            if body.get("password") == "right":
                self.user = {"name": "Prueba", "surnames": "Pruebas Test", "documentNumber": "00000000T",
                             "documentType": "1", "email": "test@example.com", "points": 10, "cashPoints": "0.10",
                             "alsaplusLevelName": "Plata"}
                return httpx.Response(200, json={"status": "success"})
            return httpx.Response(400, json={"status": "error", "errorMessage": "Contraseña incorrecta."})
        if action == "SearchJourneysAction":
            return httpx.Response(200, text="<html>results</html>", headers={"content-type": "text/html"})
        if url.path in ("/", "/home") and request.method == "GET":
            user = json.dumps(self.user) if self.user else ""
            return httpx.Response(200, text=HOME % user.replace("'", "\\'"), headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    def client(self) -> AlsaClient:
        return AlsaClient(transport=httpx.MockTransport(self.handler), persist=False)
