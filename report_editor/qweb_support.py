"""Version adapters and temporary XML placeholders, also executed in Docker.

This module needs no Odoo imports. It is bundled before docker_worker.py so the
same tested helpers run against the container's own ORM and QWeb engine.
"""
import ast
import copy
import re
import contextlib
import html
from lxml import etree


def product_label_preview_data(env, report_name, record):
    formats = {
        "product.report_producttemplatelabel": "2x7xprice",
        "product.report_producttemplatelabel2x7": "2x7xprice",
        "product.report_producttemplatelabel4x7": "4x7xprice",
        "product.report_producttemplatelabel4x12": "4x12xprice",
        "product.report_producttemplatelabel4x12noprice": "4x12",
        "product.report_producttemplatelabel_dymo": "dymo",
    }
    if report_name not in formats or record._name not in ("product.template", "product.product") or "product.label.layout" not in env:
        return None
    field = "product_tmpl_ids" if record._name == "product.template" else "product_ids"
    wizard = env["product.label.layout"].new({
        "print_format": formats[report_name], "custom_quantity": 1, field: [(6, 0, record.ids)],
    })
    _, data = wizard._prepare_report_data()


    data["layout_wizard"] = [wizard.id]

    data["quantity_by_product"] = {str(key): value for key, value in data["quantity_by_product"].items()}
    return data


def resolve_template_view(env, reference):
    views = env["ir.ui.view"]
    if isinstance(reference, int):
        return views.browse(reference).exists()
    for method in ("_get_template_view", "_get", "_get_view_id", "get_view_id"):
        resolver = getattr(views, method, None)
        if callable(resolver):
            result = resolver(reference)
            return (views.browse(result) if isinstance(result, int) else result).exists()
    view = views.search([("key", "=", reference), ("type", "=", "qweb")], limit=1)
    if view:
        return view
    view = env.ref(reference, raise_if_not_found=False)
    if not view or view._name != "ir.ui.view":
        raise ValueError("No se encuentra la plantilla QWeb: %s" % reference)
    return view.exists()


def missing_field_details(exc, operation="preview"):
    text = str(exc)
    match = re.search(r"'([^']+)' object has no attribute '([^']+)'", text)
    if operation != "preview" or not match:
        return None
    model, field = match.groups()

    if "." not in model or field.startswith("_") or field in {"get_view_id", "clear_caches", "read_combined", "get_template"}:
        return None
    if re.search(r"\b" + re.escape(field) + r"\s*\(", text):
        return None
    template = re.search(r"Template:\s*([^\n]+)", text)
    return {"model": model, "field": field, "template": template.group(1).strip() if template else ""}


def missing_field_token(exc):
    details = missing_field_details(exc)
    if details:
        return details["model"] + "." + details["field"]


    if "t-field" not in str(exc):
        return None
    cause, seen = exc, set()
    while cause and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, KeyError) and len(cause.args) == 1 and isinstance(cause.args[0], str) and cause.args[0].isidentifier():
            return "*." + cause.args[0]
        cause = cause.__cause__ or cause.__context__
    return None


def operation_error_details(exc):
    trace = str(exc)
    column = re.search(r'column [\"\']?([\w.]+)[\"\']? does not exist', trace)
    if column:
        return ("El código de Odoo espera la columna «%s», pero falta en la base de datos. Hay un módulo pendiente de actualizar o una base que no corresponde a este código." % column.group(1),
                {"kind": "schema_error", "trace": trace[:8000]})
    if "statement timeout" in trace:
        return ("La consulta ha superado los 30 segundos. Busca por #ID para acceder directamente al registro o revisa la consulta en Odoo.",
                {"kind": "query_timeout", "trace": trace[:8000]})
    template = re.search(r"Template:\s*([^\n]+)", trace)
    if template:
        lines = trace.splitlines()
        cause = next((line.strip() for line in lines if re.match(r"\s*\w+(?:Error|Exception):", line)), lines[0])
        return ("No se puede renderizar la plantilla «%s». %s" % (template.group(1).strip(), cause),
                {"kind": "template_error", "template": template.group(1).strip(), "trace": trace[:8000]})
    return None


class PlaceholderTemplates:
    """Replace absent ORM field expressions in render-only XML copies.

    Existing fields, widgets and methods remain under Odoo's control. Metadata
    follows relation fields and loop aliases, including company/user records.
    No Python expressions are evaluated here, and no model fields are patched.
    """
    def __init__(self, env, model, allowed=None):
        self.env, self.model = env, model
        self.warnings = []
        self._seen = set()
        self.scopes = []
        self.allowed = allowed
        self.failure_scopes = {}

    def record_failure(self, exc):
        details = missing_field_details(exc)
        if not details or not details["template"]:
            return


        scope = self.failure_scopes.setdefault(details["template"], {})
        for expression in re.findall(r'\bt-(?:field|out|esc|if|elif|foreach|value|att-[\w-]+)="([^"]+)"', str(exc)):
            try:
                expression = re.sub(r"\\+(['\"])", r"\1", html.unescape(expression))
                tree = ast.parse(expression, mode="eval")
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == details["field"] and isinstance(node.value, ast.Name):
                    scope[node.value.id] = details["model"]

    @contextlib.contextmanager
    def bind(self, values):
        scope = dict(self.scopes[-1]) if self.scopes else {}
        for key, value in values.items():
            try:
                model = getattr(value, "_name", None)
            except (RuntimeError, AttributeError):


                continue
            if isinstance(model, str) and model in self.env:
                scope[key] = model
        self.scopes.append(scope)
        try:
            yield
        finally:
            self.scopes.pop()

    def initial_scope(self):
        scope = {name: self.model for name in ("o", "doc", "docs")}
        scope.update({"res_company": "res.company", "company": "res.company", "user": "res.users"})
        if self.scopes:
            scope.update(self.scopes[-1])
        return scope

    def infer(self, node, scope):
        if isinstance(node, ast.Name):
            return scope.get(node.id)
        if isinstance(node, ast.Subscript):
            return self.infer(node.value, scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("sudo", "with_context", "with_company", "with_user", "filtered", "sorted", "exists"):
            return self.infer(node.func.value, scope)
        if isinstance(node, ast.Attribute):
            model = self.infer(node.value, scope)
            if model and model in self.env:
                field = self.env[model]._fields.get(node.attr)
                if field and getattr(field, "comodel_name", None):
                    return field.comodel_name
                if field is None and not hasattr(type(self.env[model]), node.attr):
                    return "?" + model + "." + node.attr
            elif model and model.startswith("?"):
                return model + "." + node.attr
        return None

    def missing(self, node, scope, check_allowed=True):
        if not isinstance(node, ast.Attribute) or node.attr.startswith("_"):
            return None
        owner = self.infer(node.value, scope)
        path = None
        if owner and owner.startswith("?"):
            path = owner[1:] + "." + node.attr
        elif owner and owner in self.env:
            record = self.env[owner]
            if node.attr not in record._fields and not hasattr(type(record), node.attr):
                path = owner + "." + node.attr
        if path and check_allowed and self.allowed is not None:
            if not any(path == key or path.startswith(key + ".") or (key.startswith("*.") and path.endswith(key[1:])) for key in self.allowed):
                return None
        return path

    def note(self, path, template, expression):
        key = (path, template, expression)
        if key not in self._seen and len(self.warnings) < 200:
            self._seen.add(key)
            self.warnings.append({"field": path, "template": str(template), "expression": expression})

    def expression(self, value, directive, scope, template):
        try:
            tree = ast.parse(value, mode="eval")
        except SyntaxError:
            return value, False
        engine = self
        changed = [False]
        edits = []

        class Replace(ast.NodeTransformer):
            def visit_Call(self, node):


                if isinstance(node.func, ast.Attribute):
                    path = engine.missing(node.func.value, scope)
                    if path:
                        changed[0] = True
                        engine.note(path, template, value)
                        replacement = repr("[%s]" % path) if directive in ("t-field", "t-out", "t-esc", "t-value") else "0"
                        edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, replacement))
                        return node

                if isinstance(node.func, ast.Attribute) and engine.missing(node.func, scope, check_allowed=False):
                    return node
                return self.generic_visit(node)

            def visit_Attribute(self, node):
                path = engine.missing(node, scope)
                if path:
                    changed[0] = True
                    engine.note(path, template, value)
                    if directive in ("t-if", "t-elif"):
                        replacement = "True"
                    elif directive == "t-foreach":
                        replacement = "[{}]"
                    elif node is tree.body and directive in ("t-field", "t-out", "t-esc"):
                        replacement = repr("[%s]" % path)
                    elif node is tree.body and directive == "t-value":
                        replacement = repr("[%s]" % path)
                    elif directive.startswith("t-att"):
                        replacement = "''"
                    elif isinstance(tree.body, ast.BinOp) and isinstance(tree.body.op, ast.Add) and any(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in ast.walk(tree)):
                        replacement = repr("[%s]" % path)
                    else:
                        replacement = "0"
                    edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, replacement))
                    return node
                return self.generic_visit(node)

        Replace().visit(tree)
        if not changed[0]:
            return value, False


        if directive in ("t-if", "t-elif"):
            return "True", True
        if directive == "t-foreach":
            return "[{}]", True
        if directive.startswith("t-att"):
            return "''", True


        raw = value.encode()
        lines = raw.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        spans = [(offsets[a - 1] + b, offsets[c - 1] + d, replacement.encode()) for a, b, c, d, replacement in edits]
        for start, end, replacement in sorted(spans, reverse=True):
            raw = raw[:start] + replacement + raw[end:]
        return raw.decode(), True

    def transform(self, source, template):
        root = copy.deepcopy(source) if isinstance(source, etree._Element) else etree.fromstring(source.encode() if isinstance(source, str) else source, etree.XMLParser(resolve_entities=False, no_network=True))

        def walk(node, scope):
            if not isinstance(node.tag, str):
                return
            local = dict(scope)
            if node.get("t-foreach"):
                try:
                    inferred = self.infer(ast.parse(node.get("t-foreach"), mode="eval").body, scope)
                    if inferred:
                        local[node.get("t-as", "item")] = inferred
                except SyntaxError:
                    pass
            if node.get("t-set"):
                try:
                    inferred = self.infer(ast.parse(node.get("t-value", "None"), mode="eval").body, scope)
                    if inferred:
                        scope[node.get("t-set")] = inferred
                        local[node.get("t-set")] = inferred
                except SyntaxError:
                    pass
            for name, value in list(node.attrib.items()):
                if name not in ("t-field", "t-out", "t-esc", "t-if", "t-elif", "t-foreach", "t-value") and not name.startswith("t-att-"):
                    continue
                expression, replaced = self.expression(value, name, local, template)
                if not replaced:
                    continue
                if name == "t-field":
                    node.attrib.pop("t-field")
                    node.attrib.pop("t-options", None)
                    for key in list(node.attrib):
                        if key.startswith("t-options-"):
                            node.attrib.pop(key)
                    name = "t-esc"
                    if node.tag in ("img", "input", "br", "hr"):
                        node.tag = "span"
                    node.set("data-editor-placeholder", "1")
                elif name in ("t-out", "t-esc"):
                    node.set("data-editor-placeholder", "1")
                node.set(name, expression)
            for child in node:
                walk(child, local)

        scope = self.initial_scope()
        for alias, model in self.failure_scopes.get(str(template), {}).items():
            scope.setdefault(alias, model)
        walk(root, scope)
        return root
