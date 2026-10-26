from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from report_editor import demo
from report_editor.app import app, sessions


HEADERS = {"X-Editor-Request": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app.state, "export_directory", tmp_path, raising=False)
    with TestClient(app) as client:
        yield client


def draft(**changes):
    return {"template_id": 1, "record_id": 1, "source": demo.TEMPLATE, **changes}


def test_demo_renders_real_fields_loops_and_alternative_record(client):
    response = client.post("/api/preview", json=draft(), headers=HEADERS)
    assert response.status_code == 200
    html = response.json()["html"]
    assert "Estudio Horizonte" in html and "Consultoría" in html and "2.649,90" in html
    assert 'data-editor-node="' in html
    other = client.post("/api/preview", json=draft(record_id=2), headers=HEADERS).json()["html"]
    assert "Taller del Mar" in other and "387,20" in other
    assert "Estudio Horizonte" not in other


def test_preview_does_not_save_and_save_checks_revision(client):
    original = client.get("/api/templates/1").json()
    changed = demo.TEMPLATE.replace("Presupuesto</h1>", "Oferta</h1>")
    assert client.post("/api/preview", json=draft(source=changed), headers=HEADERS).status_code == 200
    assert client.get("/api/templates/1").json()["source"] == original["source"]
    body = {"template_id": 1, "source": changed, "revision": original["revision"]}
    assert client.post("/api/save", json=body, headers=HEADERS).status_code == 200
    assert client.get("/api/templates/1").json()["source"] == changed
    assert client.post("/api/save", json=body, headers=HEADERS).status_code == 400


def test_sessions_are_isolated(client):
    original = client.get("/api/templates/1").json()
    client.post("/api/save", json={"template_id": 1, "source": "<t>Privado</t>", "revision": original["revision"]}, headers=HEADERS)
    with TestClient(app) as other:
        assert other.get("/api/templates/1").json()["source"] == demo.TEMPLATE


@pytest.mark.parametrize("source", [
    "<t><p></t>", '<!DOCTYPE t [<!ENTITY secret SYSTEM "file:///etc/passwd">]><t>&secret;</t>',
    '<t t-out="__import__(\'os\').getcwd()"/>', '<t t-out="o.__class__"/>', '<t t-call="web.layout"/>',
    '<t t-out="missing"/>', '<t t-attf-class="x-#{o.id}"/>',
])
def test_invalid_or_unsupported_source_has_clear_error(client, source):
    response = client.post("/api/preview", json=draft(source=source), headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]


def test_annotation_matches_element_indices_despite_comments():
    source = '<t><!-- comment --><div>Hola<br/>mundo</div></t>'
    annotated = etree.fromstring(demo.annotate(source).encode())
    assert [node.get("data-editor-node") for node in annotated.iter() if isinstance(node.tag, str)] == [None, "1", "2"]


def test_escape_values_in_demo():
    assert demo.render('<t><p t-out="\'&lt;script&gt;\'"/></t>', 1) == '<p data-editor-node="1">&lt;script&gt;</p>'


def test_csrf_and_untrusted_hosts_are_rejected(client):
    assert client.post("/api/preview", json=draft()).status_code == 403
    assert client.post("/api/preview", json=draft(), headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_parallel_saves_only_accept_one_revision(client):
    current = client.get("/api/templates/1").json()
    body = {"template_id": 1, "source": "<t>Version nueva</t>", "revision": current["revision"]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post("/api/save", json=body, headers=HEADERS).status_code, range(2)))
    assert sorted(results) == [200, 400]


def test_docker_is_used_for_preview_but_save_only_exports(client, tmp_path):
    from types import SimpleNamespace
    from pathlib import Path

    class Remote:
        url = "https://odoo.example"
        version = "18.0"
        project = SimpleNamespace(directory=tmp_path, service="odoo")

        def call(self, method, *args):
            if method == "preview":
                assert 'data-editor-node="' in args[2]
                return "<p>Desde Odoo</p>"
            if method == "get_template":
                return {"id": 1, "name": "Presupuesto", "key": "sale.order_report", "revision": "initial"}
            raise AssertionError(method)

    client.get("/api/status")
    current = sessions[client.cookies["editor_session"]]
    current.client = Remote()
    response = client.post("/api/preview", json=draft(), headers=HEADERS)
    assert response.json() == {"html": "<p>Desde Odoo</p>", "base_url": "https://odoo.example"}
    result = client.post("/api/save", json={"template_id": 1, "source": demo.TEMPLATE, "revision": "initial"}, headers=HEADERS)
    assert result.json()["revision"] == "initial"
    exported = Path(result.json()["path"])
    assert exported.parent == tmp_path / "report_editor_exports"
    assert etree.parse(str(exported)).getroot().tag == "odoo"


def test_ui_assets_exist(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/source-map.js").status_code == 200
    assert client.get("/static/pagination.js").status_code == 200


def test_pdf_preview_is_private_and_replaced_by_each_render(client):
    import base64

    class Remote:
        url = "http://localhost:8069"

        def call(self, method, *args):
            assert method == "preview"
            assert args[-1]["editor_format"] == "pdf"
            return {"pdf": base64.b64encode(b"%PDF-1.4\npreview").decode(), "warnings": []}

    client.get("/api/status")
    sessions[client.cookies["editor_session"]].client = Remote()
    result = client.post("/api/preview", json=draft(format="pdf"), headers=HEADERS).json()
    url = result["pdf_url"]
    response = client.get(url)
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    with TestClient(app) as other:
        assert other.get(url).status_code == 404
    client.post("/api/preview", json=draft(format="pdf"), headers=HEADERS)
    assert client.get(url).status_code == 404


def test_pdf_demo_reports_that_odoo_is_required(client):
    response = client.post("/api/preview", json=draft(format="pdf"), headers=HEADERS)
    assert response.status_code == 400
    assert "Odoo" in response.json()["detail"]


def test_odoo_paper_margins_are_forwarded_to_preview(client):
    class Remote:
        url = "http://localhost:18069"

        def call(self, method, *args):
            assert method == "preview"
            return {"html": "<p>Documento</p>", "paper": {"margins": {"top": 40, "right": 7, "bottom": 25, "left": 7}}}

    client.get("/api/status")
    sessions[client.cookies["editor_session"]].client = Remote()
    response = client.post("/api/preview", json=draft(), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["paper"]["margins"] == {"top": 40, "right": 7, "bottom": 25, "left": 7}


def test_record_search_finds_database_identifier_and_reference(client):
    assert [row["id"] for row in client.get("/api/records?q=%232").json()] == [2]
    assert [row["id"] for row in client.get("/api/records?q=1").json()] == [1]
    assert [row["id"] for row in client.get("/api/records?q=S00043").json()] == [2]
    assert client.get("/api/records?q=unknown").json() == []


def test_reports_include_action_name_template_and_model(client):
    report = client.get("/api/reports").json()[0]
    assert report["model"] == "sale.order"
    assert report["name"] and report["key"] and report["model_name"]


def test_missing_field_error_has_separate_diagnostic_and_trace(client):
    from report_editor.project import OdooOperationError

    class BrokenOdoo:
        url = "http://localhost:8069"

        def call(self, *args):
            raise OdooOperationError("Falta el campo order_ref en repair.order.", {
                "kind": "missing_field", "field": "order_ref", "model": "repair.order",
                "template": "gv_repair.report_stock_picking_not_valued_document", "trace": "Technical traceback",
                "dependencies": [{"module": "llorsa_repair_security", "state": "not_registered"}],
            })

    client.get("/api/status")
    sessions[client.cookies["editor_session"]].client = BrokenOdoo()
    response = client.post("/api/preview", json=draft(), headers=HEADERS)
    assert response.status_code == 400
    assert "Technical traceback" not in response.json()["detail"]
    assert response.json()["diagnostic"]["field"] == "order_ref"


def test_placeholder_preview_supports_missing_related_fields_and_can_be_disabled(client):
    source = '<t><p t-field="o.order_ref"/><p t-field="o.partner_id.custom_code"/></t>'
    response = client.post("/api/preview", json=draft(source=source), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["placeholder_mode"] is True
    assert "[sale.order.order_ref]" in response.json()["html"]
    assert "[res.partner.custom_code]" in response.json()["html"]
    assert len(response.json()["warnings"]) == 2
    assert client.post("/api/preview", json=draft(source=source, placeholders=False), headers=HEADERS).status_code == 400
    assert client.get("/api/templates/1").json()["source"] == demo.TEMPLATE
    original = client.get("/api/templates/1").json()
    saved = client.post("/api/save", json={"template_id": 1, "source": source, "revision": original["revision"]}, headers=HEADERS).json()
    assert 't-field="o.order_ref"' in saved["xml"]
    assert "[sale.order.order_ref]" not in saved["xml"]
    assert "data-editor-placeholder" not in saved["xml"]
