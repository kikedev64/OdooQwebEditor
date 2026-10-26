"""Runs inside Odoo's container, using its installed Python and addons.

Only this private process is patched; no module installation or DB writes are
needed to substitute draft architectures. Requests always end in rollback.
"""
import contextlib
import inspect
import json
import os
import sys
import time
import hashlib
import shutil
import configparser
import re


protocol = sys.stdout


def reply(result=None, error=None, diagnostic=None):
    protocol.write("QWEB_EDITOR:" + json.dumps({"ok": error is None, "result": result, "error": error, "diagnostic": diagnostic}, default=str) + "\n")
    protocol.flush()


try:
    startup = json.loads(sys.stdin.readline()).get("startup", [])
    with contextlib.redirect_stdout(sys.stderr):
        executable = shutil.which("odoo") or shutil.which("odoo-bin")
        if executable:
            sys.path.insert(0, os.path.dirname(os.path.realpath(executable)))
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.tools import config
        from odoo.modules.registry import Registry
        from lxml import etree

        if not any(arg in ("-c", "--config") or arg.startswith("--config=") for arg in startup):
            path = os.environ.get("ODOO_RC", "/etc/odoo/odoo.conf")
            if os.path.isfile(path):
                startup = ["-c", path] + startup
        configuration_path = None
        for index, arg in enumerate(startup):
            if arg in ("-c", "--config") and index + 1 < len(startup):
                configuration_path = startup[index + 1]
            elif arg.startswith("--config="):
                configuration_path = arg.split("=", 1)[1]
        file_config = configparser.RawConfigParser()
        if configuration_path:
            file_config.read(configuration_path)
        file_options = dict(file_config.items("options")) if file_config.has_section("options") else {}
        if "setup_logging" in inspect.signature(config.parse_config).parameters:
            config.parse_config(startup + ["--no-http"], setup_logging=False)
        else:
            config.parse_config(startup + ["--no-http"])


        environment = {"db_host": ("HOST", "DB_HOST", "PGHOST"), "db_port": ("PORT", "DB_PORT", "PGPORT"),
                       "db_user": ("USER", "DB_USER", "PGUSER"), "db_password": ("PASSWORD", "DB_PASSWORD", "PGPASSWORD")}
        explicit = {arg.split("=", 1)[0] for arg in startup}
        for key, names in environment.items():
            if "--" + key in explicit or file_options.get(key, "").strip().lower() not in ("", "false", "none"):
                continue
            value = next((os.environ[name] for name in names if os.environ.get(name)), None)

            if key == "db_user" and value == "root":
                value = next((os.environ[name] for name in ("DB_USER", "PGUSER") if os.environ.get(name)), None)
            if key == "db_password" and os.environ.get("PASSWORD_FILE"):
                with open(os.environ["PASSWORD_FILE"]) as handle:
                    value = handle.read().strip()
            if value:
                config[key] = int(value) if key == "db_port" else value
        import odoo.service.server
        odoo.service.server.load_server_wide_modules()
except Exception as exc:
    reply(error="No se pudo inicializar Odoo en el contenedor: " + str(exc)[:1000])
    sys.exit(1)


active_draft = None
active_placeholders = None
patched = set()


def missing_dependencies(env, modules):
    """Explain why an installed addon's Python models were not loaded."""
    issues, seen = [], set()
    loader = getattr(odoo.modules.module, "get_manifest", None) or odoo.modules.module.load_information_from_description_file

    def visit(name, chain):
        if name in seen or len(issues) >= 5:
            return
        seen.add(name)
        module = env["ir.module.module"].search([("name", "=", name)], limit=1)
        if not module or module.state != "installed":
            issues.append({"module": name, "state": module.state if module else "not_registered", "chain": chain + [name]})
            return
        for dependency in (loader(name) or {}).get("depends", []):
            visit(dependency, chain + [name])

    for name in modules:
        visit(name, [])
    return issues


def patch_views(env):
    cls = type(env["ir.ui.view"])
    if cls in patched:
        return
    def inject(self):
        if active_draft:
            view = self.browse(active_draft["id"])


            self.env.cache.set(view, view._fields["arch_db"], active_draft["source"])
            self.env.cache.set(view, view._fields["arch"], active_draft["source"])
    if hasattr(cls, "_get_view_etrees"):
        original = cls._get_view_etrees

        def get_view_etrees(self):
            inject(self)
            trees = original(self)
            if active_placeholders:
                return [active_placeholders.transform(tree, view.key or view.id) for view, tree in zip(self, trees)]
            return trees

        cls._get_view_etrees = get_view_etrees
    elif hasattr(cls, "_read_template"):
        original = cls._read_template

        def read_template(self, view_id, *args, **kwargs):
            inject(self)
            source = original(self, view_id, *args, **kwargs)
            if active_placeholders:
                source = etree.tostring(active_placeholders.transform(source, self.browse(view_id).key or view_id), encoding="unicode")
            return source

        cls._read_template = read_template
    else:
        raise ValueError("Esta versión de Odoo no ofrece un cargador de plantillas compatible con el editor.")
    qweb_cls = type(env["ir.qweb"])
    render_original = qweb_cls._render

    def render_with_scope(self, template, values=None, **options):
        if active_placeholders:
            with active_placeholders.bind(values or {}):
                return render_original(self, template, values, **options)
        return render_original(self, template, values, **options)

    qweb_cls._render = render_with_scope
    patched.add(cls)


def clear_templates(env):
    if hasattr(env.registry, "clear_cache"):


        env.registry.clear_cache("templates")
    else:
        env["ir.ui.view"].clear_caches()


def get_view(env, reference):
    return resolve_template_view(env, reference)


def template_info(view):
    xml_id = view.get_external_id().get(view.id) or ""
    parent = view.inherit_id
    return {"id": view.id, "name": view.name, "key": view.key or xml_id,
            "xml_id": xml_id, "source": view.arch_db,
            "revision": hashlib.sha256(str(view.arch_db).encode()).hexdigest(),
            "inherited": bool(parent), "inherit_xml_id": parent.get_external_id().get(parent.id, "") if parent else "",
            "view_mode": view.mode}


def available_databases(requested):
    from odoo.service.db import list_dbs
    configured = config["db_name"] or []
    if isinstance(configured, str):
        configured = [name.strip() for name in configured.split(",") if name.strip()]
    candidates = [requested] if requested else configured or list_dbs(force=True)
    result = []
    for name in candidates:
        try:
            with odoo.sql_db.db_connect(name).cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.ir_module_module')")
                if cursor.fetchone()[0]:
                    result.append(name)
                cursor.rollback()
        except Exception:
            if requested:
                raise
    return result


def handle(method, args, env):
    global active_draft, active_placeholders
    if method == "base_url":
        return env["ir.config_parameter"].sudo().get_param("web.base.url", "")
    if method == "list_reports":
        rows = env["ir.actions.report"].search([("report_type", "in", ["qweb-html", "qweb-pdf"])], order="name")
        return [{"id": row.id, "name": row.name, "model": row.model, "model_name": env[row.model]._description if row.model in env else row.model,
                 "key": row.report_name, "report_type": row.report_type} for row in rows if row.model in env]
    if method == "diagnose_field":
        model, field, module = args
        loaded = sys.modules.get("odoo.addons." + module)
        loader = getattr(odoo.modules.module, "get_manifest", None) or odoo.modules.module.load_information_from_description_file
        manifest = loader(module)
        return {"present": field in env[model]._fields,
                "python_module": getattr(loaded, "__file__", None),
                "repair_model_loaded": "odoo.addons." + module + ".models.repair_order" in sys.modules,
                "module": env["ir.module.module"].search_read([("name", "=", module)], ["name", "state"]),
                "dependencies": env["ir.module.module"].search_read([("name", "in", manifest.get("depends", []))], ["name", "state"])}
    if method == "list_templates":
        query, report_id = (args + ["", None])[:2] if len(args) < 2 else args[:2]
        if not report_id:
            domain = [("type", "=", "qweb"), ("inherit_id", "=", False)]
            if query:
                domain += ["|", ("name", "ilike", query), ("key", "ilike", query)]
            return [{"id": v.id, "name": v.name, "key": v.key or "", "model": ""} for v in env["ir.ui.view"].search(domain, limit=300, order="name")]
        report = env["ir.actions.report"].browse(int(report_id)).exists()
        if not report:
            raise ValueError("El informe ya no existe.")
        seen, rows = set(), []

        def visit(reference):
            if len(seen) >= 80:
                return
            try:
                view = get_view(env, reference)
            except (ValueError, KeyError):
                return
            if not view or view.id in seen:
                return
            seen.add(view.id)
            arch = etree.fromstring(view.arch_db.encode())
            key = view.key or str(reference)
            if (not key.startswith("web.") or reference == report.report_name) and not view.inherit_id:
                score = 20 * bool(arch.xpath("//*[@t-field]")) + 30 * bool(arch.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' page ')]"))


                if key.split(".", 1)[0] != report.report_name.split(".", 1)[0]:
                    score -= 60
                rows.append({"id": view.id, "name": view.name, "key": key, "model": report.model, "report_id": report.id, "score": score})
            for node in arch.xpath("//*[@t-call]"):
                call = node.get("t-call")
                if call and not call.startswith("web."):
                    visit(call)

        visit(report.report_name)
        rows.sort(key=lambda row: -row.pop("score"))
        return [row for row in rows if not query or query.lower() in (row["name"] + row["key"]).lower()]
    if method == "get_template":
        view = env["ir.ui.view"].browse(int(args[0])).exists()
        if not view or view.type != "qweb":
            raise ValueError("Plantilla QWeb no encontrada.")
        return template_info(view)
    if method == "list_records":
        model, query = args
        if model not in env:
            raise ValueError("Modelo desconocido.")
        model_obj = env[model]
        query = (query or "").strip()
        found = model_obj.browse()
        numeric = query.lstrip("#")
        if numeric.isdecimal():
            found |= model_obj.browse(int(numeric)).exists()
            if found or query.startswith("#"):
                return [{"id": row.id, "display_name": row.display_name} for row in found]
        if query and hasattr(model_obj, "name_search"):
            found |= model_obj.browse([ident for ident, _ in model_obj.name_search(query, limit=50)])
        conditions = [(name, "ilike", query) for name in ("name", "ref", "reference", "default_code", "client_order_ref", "origin", "order_ref")
                      if name in model_obj._fields and model_obj._fields[name].type in ("char", "text")
                      and (model_obj._fields[name].store or model_obj._fields[name].search)]
        if "partner_id" in model_obj._fields and model_obj._fields["partner_id"].type == "many2one":
            conditions.append(("partner_id.name", "ilike", query))
        domain = ["|"] * (len(conditions) - 1) + conditions if conditions and query else []
        if conditions or not query:
            found |= model_obj.search(domain, limit=50, order="id desc")
        return [{"id": row.id, "display_name": row.display_name} for row in found[:50]]
    if method == "list_fields":
        fields = env[args[0]].fields_get(attributes=["string", "type", "relation"])
        return [{"name": name, **value} for name, value in sorted(fields.items()) if value["type"] not in ("one2many", "many2many", "binary")]
    if method == "preview":
        view_id, record_id, source, model, report_id, context = args
        context = context or {}
        pdf_mode = context.get("editor_format") == "pdf"
        if pdf_mode and not report_id:
            raise ValueError("Selecciona una acción de informe PDF para ver el resultado final.")
        env = env(context={**env.context, **{key: value for key, value in context.items() if not key.startswith("editor_")}})
        record = env[model].browse(int(record_id)).exists()
        if not record:
            raise ValueError("El registro de ejemplo ya no existe.")
        patch_views(env)
        clear_templates(env)
        active_draft = {"id": int(view_id), "source": source}
        resource_warnings = []
        def render():
            if report_id:
                report = env["ir.actions.report"].browse(int(report_id)).exists()
                if not report or report.model != model:
                    raise ValueError("El informe y el registro deben utilizar el mismo modelo.")
                data = product_label_preview_data(env, report.report_name, record)
                if pdf_mode:
                    if report.report_type != "qweb-pdf":
                        raise ValueError("Esta acción es un informe HTML; selecciona Edición visual.")
                    report = report.with_context(report_pdf_no_attachment=True, commit_assetsbundle=False,
                                                 force_report_rendering=True)
                    env.cache.set(report, report._fields["attachment_use"], False)
                    env.cache.set(report, report._fields["attachment"], False)
                    parameters = inspect.signature(report._render_qweb_pdf).parameters
                    report_class = type(report)
                    original_prepare = report_class._prepare_html
                    def prepare_with_resources(reports, document, *prepare_args, **prepare_kwargs):
                        prepared = list(original_prepare(reports, document, *prepare_args, **prepare_kwargs))
                        def embed(document):
                            if not document:
                                return document
                            embedded, warnings = embed_report_resources(
                                document, lambda url: odoo_report_resource(reports.env, url),
                                reports.env["ir.config_parameter"].sudo().get_param("web.base.url", ""))
                            resource_warnings.extend(warnings)
                            return embedded.encode("utf-8")
                        prepared[0] = [embed(body) for body in prepared[0]]
                        prepared[2], prepared[3] = embed(prepared[2]), embed(prepared[3])
                        return tuple(prepared)
                    report_class._prepare_html = prepare_with_resources
                    try:
                        if "report_ref" in parameters:
                            return report._render_qweb_pdf(report.id, [record.id], data=data)[0]
                        return report._render_qweb_pdf([record.id], data=data)[0]
                    finally:
                        report_class._prepare_html = original_prepare
                parameters = inspect.signature(report._render_qweb_html).parameters
                if "report_ref" in parameters:
                    return report._render_qweb_html(report.id, [record.id], data=data)[0]
                return report._render_qweb_html([record.id], data=data)[0]
            values = {"docs": record, "doc_ids": record.ids, "doc_model": model, "o": record, "doc": record,
                      "user": env.user, "res_company": env.company, "time": time}
            return env["ir.ui.view"]._render_template(int(view_id), values)

        try:
            allowed = set()
            for attempt in range(33):
                clear_templates(env)
                try:
                    with env.cr.savepoint():
                        result = render()
                    break
                except Exception as exc:
                    token = missing_field_token(exc)
                    if not (context or {}).get("editor_placeholders", True) or not token or token in allowed:
                        raise
                    allowed.add(token)
                    if active_placeholders is None:
                        active_placeholders = PlaceholderTemplates(env, model, allowed=allowed)
                    active_placeholders.record_failure(exc)
            else:
                raise ValueError("La plantilla requiere más de 32 sustituciones. Corrige algunos campos o desactiva Campos de ejemplo para localizar el siguiente error.")
            if pdf_mode:
                if not isinstance(result, bytes) or not result.startswith(b"%PDF-"):
                    raise ValueError("Odoo no ha devuelto un PDF válido.")
                return {"pdf": base64.b64encode(result).decode(),
                        "warnings": active_placeholders.warnings if active_placeholders else [],
                        "resource_warnings": resource_warnings,
                        "placeholder_mode": bool(active_placeholders)}
            output = result.decode() if isinstance(result, bytes) else str(result)
            if "data-editor-node" not in output:
                root = etree.fromstring(source.encode())
                if any(isinstance(node.tag, str) and node.tag not in ("t", "template", "data", "xpath") for node in root.iter()):
                    raise ValueError("El informe no ha mostrado la plantilla seleccionada con este registro. Selecciona otra plantilla del informe o un registro que active esa parte del documento.")
            paper = env["ir.actions.report"].browse(int(report_id)).get_paperformat() if report_id else env.company.paperformat_id
            margins = {side: getattr(paper, "margin_" + side, 0) for side in ("top", "right", "bottom", "left")}
            output, resource_warnings = embed_report_resources(
                output, lambda url: odoo_report_resource(env, url),
                env["ir.config_parameter"].sudo().get_param("web.base.url", ""))
            return {"html": output, "warnings": active_placeholders.warnings if active_placeholders else [], "placeholder_mode": bool(active_placeholders),
                    "resource_warnings": resource_warnings,
                    "paper": {"margins": margins, "header_spacing": getattr(paper, "header_spacing", 0)}}
        except Exception as exc:
            match = re.search(r"Template:\s*([\w.]+)", str(exc))
            if match and "object has no attribute" in str(exc):
                try:
                    exc.editor_dependency_issues = missing_dependencies(env, [match.group(1).split(".", 1)[0]])
                except Exception:
                    pass
            raise
        finally:
            active_draft = None
            active_placeholders = None
            clear_templates(env)
    raise ValueError("Operación desconocida.")


for line in sys.stdin:
    try:
        request = json.loads(line)
        with contextlib.redirect_stdout(sys.stderr):
            method, args = request["method"], request.get("args", [])
            database = request.get("database")
            if method == "inspect":
                databases = available_databases(database)
                result = {"databases": databases, "database": database or (databases[0] if len(databases) == 1 else None), "version": odoo.release.version}
                if not databases:
                    raise ValueError("No se encontró una base de datos Odoo. Revisa odoo.conf, las variables de conexión o utiliza --database NOMBRE.")
            else:
                if not database:
                    raise ValueError("Selecciona una base de datos del proyecto.")
                manager = api.Environment.manage() if hasattr(api.Environment, "manage") else contextlib.nullcontext()
                with manager, Registry(database).cursor() as cursor:
                    try:
                        cursor.execute("SET LOCAL statement_timeout = '30000ms'")


                        env = api.Environment(cursor, SUPERUSER_ID, {"prefetch_fields": False})
                        env = api.Environment(cursor, SUPERUSER_ID, {**env["res.users"].context_get(), "prefetch_fields": False})
                        result = handle(method, args, env)
                    finally:
                        cursor.rollback()
        reply(result)
    except Exception as exc:
        text = str(exc)
        missing = missing_field_details(exc, request.get("method", ""))
        if missing:
            model, field = missing["model"], missing["field"]
            template_match = re.search(r"Template:\s*([^\n]+)", text)
            template_name = template_match.group(1).strip() if template_match else ""
            issues = getattr(exc, "editor_dependency_issues", [])
            diagnostic = {"kind": "missing_field", "model": model, "field": field, "template": template_name, "trace": text[:8000], "dependencies": issues}
            message = f"La plantilla {template_name or 'seleccionada'} utiliza el campo «{field}», pero no existe en el modelo «{model}» cargado por Odoo."
            if issues:
                message += "\nHay dependencias pendientes: " + ", ".join(issue["module"] for issue in issues) + ". Revisa estos módulos en Odoo y vuelve a iniciar el editor."
            else:
                message += " Revisa el módulo que lo define o corrige esa referencia en el borrador."
            reply(error=message, diagnostic=diagnostic)
        else:
            details = operation_error_details(exc)
            if details:
                reply(error=details[0], diagnostic=details[1])
            else:
                reply(error=text[:2000])
