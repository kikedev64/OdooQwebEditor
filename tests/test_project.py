import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lxml import etree

from report_editor import demo
from report_editor.project import ComposeProject, DockerOdooClient, export_template


def configuration(tmp_path, monkeypatch, services):
    (tmp_path / "docker-compose.yml").write_text("services: {}")
    monkeypatch.setattr("report_editor.project.shutil.which", lambda name: "/usr/bin/docker")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"services": services})))
    monkeypatch.setattr("report_editor.project.subprocess.run", run)
    return run


def test_discover_service_connection_options_and_published_port(tmp_path, monkeypatch):
    run = configuration(tmp_path, monkeypatch, {
        "db": {"image": "postgres:16"},
        "odoo_proxy": {"image": "odoo-proxy"},
        "odoo": {"image": "odoo:18", "command": ["odoo", "-c", "/etc/odoo/odoo.conf", "-d", "example", "--workers", "4"],
                 "ports": [{"target": 8069, "published": "18069"}]},
    })
    project = ComposeProject.discover(tmp_path)
    assert project.service == "odoo" and project.url == "http://127.0.0.1:18069"
    assert project.startup == ["-c", "/etc/odoo/odoo.conf", "-d", "example"]
    args = run.call_args.args[0]
    assert args == ["docker", "compose", "--project-directory", str(tmp_path), "config", "--format", "json"]
    assert "shell" not in run.call_args.kwargs


def test_ambiguous_services_can_be_selected_explicitly(tmp_path, monkeypatch):
    configuration(tmp_path, monkeypatch, {"erp_a": {"image": "odoo:17"}, "erp_b": {"image": "odoo:18"}})
    with pytest.raises(ValueError, match="--service"):
        ComposeProject.discover(tmp_path)
    assert ComposeProject.discover(tmp_path, service="erp_b").service == "erp_b"
    with pytest.raises(ValueError, match="no existe"):
        ComposeProject.discover(tmp_path, service="missing")


def test_missing_compose_and_invalid_config_do_not_fall_back_to_demo(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Docker Compose"):
        ComposeProject.discover(tmp_path)
    run = configuration(tmp_path, monkeypatch, {})
    run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="sensitive information")
    with pytest.raises(ValueError) as exc:
        ComposeProject.discover(tmp_path)
    assert "sensitive information" not in str(exc.value)


def test_custom_file_and_string_command(tmp_path, monkeypatch):
    configuration(tmp_path, monkeypatch, {"web": {"image": "odoo:18", "command": 'odoo --config="/config/my odoo.conf" --database=demo'}})
    (tmp_path / "development.yml").write_text("services: {}")
    project = ComposeProject.discover(tmp_path, compose_file="development.yml")
    assert project.compose[-2:] == ["-f", str(tmp_path / "development.yml")]
    assert project.startup == ["--config=/config/my odoo.conf", "--database=demo"]


def test_shell_command_does_not_confuse_shell_c_with_odoo_config(tmp_path, monkeypatch):
    configuration(tmp_path, monkeypatch, {"odoo": {"image": "odoo:18", "command": ["bash", "-c", "odoo -c /config/odoo.conf -d demo --dev=all"]}})
    project = ComposeProject.discover(tmp_path)
    assert project.startup == ["-c", "/config/odoo.conf", "-d", "demo"]


def test_worker_protocol_ignores_logs_and_does_not_put_startup_secrets_in_command(tmp_path, monkeypatch):
    config = {"databases": ["demo"], "database": "demo", "version": "18.0"}
    output = 'Odoo startup log\nQWEB_EDITOR:' + json.dumps({"ok": True, "result": config}) + '\n'
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(output), poll=lambda: None, wait=lambda timeout: None)
    popen = Mock(return_value=process)
    monkeypatch.setattr("report_editor.project.subprocess.Popen", popen)
    monkeypatch.setattr("report_editor.project.subprocess.run", Mock(return_value=SimpleNamespace(returncode=0, stdout="container-id\n")))
    project = ComposeProject(tmp_path, ["docker", "compose"], "odoo", ["--db_password", "secret"], "http://localhost:8069")
    client = DockerOdooClient(project)
    try:
        assert client.inspect() == config
        assert client.database == "demo"
        assert popen.call_args.args[0][:4] == ["docker", "exec", "-i", "container-id"]
        assert "secret" not in str(popen.call_args.args[0])
        assert "secret" in process.stdin.getvalue()
        with pytest.raises(ValueError, match="detectadas"):
            client.for_database("other")
    finally:
        client.close()


def test_worker_finds_compose_run_container_without_starting_services(tmp_path, monkeypatch):
    run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=""), SimpleNamespace(returncode=0, stdout="one-off-id\n")])
    monkeypatch.setattr("report_editor.project.subprocess.run", run)
    client = DockerOdooClient(ComposeProject(tmp_path, ["docker", "compose"], "odoo", [], ""))
    assert client._running_container() == "one-off-id"
    assert run.call_args_list[1].args[0] == ["docker", "compose", "ps", "--all", "--status", "running", "--quiet", "odoo"]


@pytest.mark.parametrize("outputs, message", [
    (["", ""], "está parado"),
    (["", "container-a\ncontainer-b\n"], "varios contenedores"),
])
def test_unavailable_or_ambiguous_container_has_actionable_error(tmp_path, monkeypatch, outputs, message):
    monkeypatch.setattr("report_editor.project.subprocess.run", Mock(side_effect=[SimpleNamespace(returncode=0, stdout=value) for value in outputs]))
    client = DockerOdooClient(ComposeProject(tmp_path, ["docker", "compose"], "odoo", [], ""))
    with pytest.raises(ValueError, match=message):
        client.inspect()
    assert client.process is None


def test_export_is_importable_preserves_qweb_and_never_overwrites(tmp_path):
    template = {"id": 7, "name": "Pedido", "key": "sale.report_saleorder_document", "xml_id": "sale.report_saleorder_document"}
    first = export_template(tmp_path, template, demo.annotate(demo.TEMPLATE))
    second = export_template(tmp_path, template, demo.TEMPLATE)
    assert first["path"] != second["path"]
    root = etree.parse(first["path"]).getroot()
    record = root.find("record")
    assert record.get("id") == "sale.report_saleorder_document"
    assert record.find("field[@name='arch']/t").get("t-name") == "demo.sale_order"
    assert root.xpath("//*[@t-field='o.name']")
    assert "data-editor-node" not in first["xml"]
    assert Path(first["path"]).parent == tmp_path / "report_editor_exports"


def test_export_inherited_view_references_parent_and_rejects_unsafe_xml(tmp_path):

    result = export_template(tmp_path, {"id": 1, "name": "Custom", "key": "custom.report", "inherited": True,
                             "inherit_xml_id": "sale.report_saleorder_document", "view_mode": "extension"},
                             '<xpath expr="//h1" position="replace"><h1>Hola</h1></xpath>')
    assert 'ref="sale.report_saleorder_document"' in result["xml"]
    with pytest.raises(ValueError):
        export_template(tmp_path, {"id": 1, "name": "Test"}, '<!DOCTYPE t [<!ENTITY s SYSTEM "file:///etc/passwd">]><t>&s;</t>')
