from queguagua.alsa import manage

AMEND = """
<a class="void icn-angle-right" href="https://www.alsa.es/gestion-de-billetes/cambios-y-anulaciones?p_p_id=AmendmentPortlet_WAR_Alsaportlet&amp;p_p_lifecycle=1&amp;_AmendmentPortlet_WAR_Alsaportlet_javax.portlet.action=voidTicketActionNavegalia&amp;p_auth=x&amp;_AmendmentPortlet_WAR_Alsaportlet_checksum=$6$abc&amp;_AmendmentPortlet_WAR_Alsaportlet_pos=0" data-test-id="cancelTicketButton">
<a class="change icn-angle-right" href="https://www.alsa.es/x?_AmendmentPortlet_WAR_Alsaportlet_javax.portlet.action=changeTicketAction&amp;_AmendmentPortlet_WAR_Alsaportlet_checksum=$6$abc&amp;_AmendmentPortlet_WAR_Alsaportlet_pos=0">
<a class="change icn-angle-right" href="https://www.alsa.es/x?_AmendmentPortlet_WAR_Alsaportlet_javax.portlet.action=changeHolderAction&amp;_AmendmentPortlet_WAR_Alsaportlet_checksum=$6$abc&amp;_AmendmentPortlet_WAR_Alsaportlet_pos=0">
"""


def test_ticket_options_are_grouped_by_checksum():
    rows = manage._options(AMEND)
    assert len(rows) == 1
    assert {"void", "change", "holder"} <= set(rows[0])
    assert "&amp;" not in rows[0]["void"]


def test_money_labels():
    body = "Precio del recargo: <span>1,50</span> Importe a devolver <b>21.78</b> Costes de gestión: 0 &euro;"
    assert manage._money(body, "Precio del recargo") == 1.5
    assert manage._money(body, "Importe a devolver") == 21.78
    assert manage._money(body, "Costes de gestión") == 0.0
