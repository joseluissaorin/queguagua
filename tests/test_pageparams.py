from queguagua.alsa import pageparams


def test_parses_namespaced_json_and_plain_values():
    html = """<script>
    params.purchase["jsonCart"] = '{"totalAmount": 23.28, "name": "Básica \\u00c1"}';
    params.journeySearch["getOriginsURL"] = 'https://www.alsa.es/home?a=1\\x26b=2';
    params["tabUUID"] = "6972ea9c";
    params.purchase["empty"] = '';
    Liferay.authToken = 'Cad1LTWp';
    </script>"""
    p = pageparams.parse(html)
    assert p["purchase"]["jsonCart"] == {"totalAmount": 23.28, "name": "Básica Á"}
    assert p["journeySearch"]["getOriginsURL"] == "https://www.alsa.es/home?a=1&b=2"
    assert p[""]["tabUUID"] == "6972ea9c"
    assert p["purchase"]["empty"] == ""
    assert pageparams.auth_token(html) == "Cad1LTWp"


def test_escaped_quotes_inside_json():
    html = "params.x[\"j\"] = '{\"a\": \"it\\'s\"}';"
    assert pageparams.parse(html)["x"]["j"] == {"a": "it's"}


def test_auth_token_from_url_when_no_liferay_global():
    assert pageparams.auth_token('href="/checkout?p_auth=Zz9Yy8Xx&x=1"') == "Zz9Yy8Xx"
