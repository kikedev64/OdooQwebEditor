"""Render a limited QWeb demo without executing user Python code."""
import ast
import copy
import html
from lxml import etree


TEMPLATE = '''<t t-name="demo.sale_order">
  <div class="page" style="font-family:Arial,sans-serif;color:#243348;padding:48px;">
    <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:40px;">
      <div><h2 style="color:#d9363e;margin:0;">NORTHWIND</h2><p style="color:#8792a2;">Diseñamos lo que viene.</p></div>
      <div style="text-align:right;"><h1 style="font-size:28px;margin:0;">Presupuesto</h1><p t-field="o.name"/></div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-bottom:32px;">
      <div><p style="font-size:11px;color:#8792a2;">PREPARADO PARA</p><strong t-field="o.partner_id.name"/><p t-field="o.partner_id.street"/><p t-field="o.partner_id.city"/></div>
      <div><p style="font-size:11px;color:#8792a2;">FECHA DE EMISIÓN</p><span t-field="o.date_order"/></div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="background:#fff0f1;text-align:left;"><th style="padding:14px;">Descripción</th><th>Cantidad</th><th>Precio</th><th>Importe</th></tr></thead>
      <tbody><tr t-foreach="o.order_line" t-as="line" style="border-bottom:1px solid #edf0f4;"><td style="padding:18px 14px;" t-field="line.name"/><td t-field="line.product_uom_qty"/><td><span t-field="line.price_unit"/> €</td><td><span t-field="line.price_subtotal"/> €</td></tr></tbody>
    </table>
    <div style="margin:28px 0 44px auto;width:240px;text-align:right;"><p>Base imponible: <span t-field="o.amount_untaxed"/> €</p><p>IVA (21%): <span t-field="o.amount_tax"/> €</p><h2 style="color:#d9363e;">Total: <span t-field="o.amount_total"/> €</h2></div>
    <div style="border-top:1px solid #e7e9ef;padding-top:20px;color:#8792a2;font-size:12px;"><p>Gracias por confiar en nuestro equipo.</p><p>Validez del presupuesto: 30 días · Pago por transferencia bancaria</p></div>
  </div>
</t>'''

RECORDS = [
    {"id": 1, "display_name": "S00042 · Estudio Horizonte", "name": "S00042",
     "partner_id": {"name": "Estudio Horizonte, S.L.", "street": "Carrer de Provença, 128", "city": "08036 Barcelona"},
     "date_order": "22/10/2026", "order_line": [
         {"name": "Consultoría y diseño de procesos", "product_uom_qty": 8, "price_unit": "85,00", "price_subtotal": "680,00"},
         {"name": "Implementación de Odoo", "product_uom_qty": 1, "price_unit": "1.250,00", "price_subtotal": "1.250,00"},
         {"name": "Formación del equipo", "product_uom_qty": 4, "price_unit": "65,00", "price_subtotal": "260,00"}],
     "amount_untaxed": "2.190,00", "amount_tax": "459,90", "amount_total": "2.649,90"},
    {"id": 2, "display_name": "S00043 · Taller del Mar", "name": "S00043",
     "partner_id": {"name": "Taller del Mar", "street": "Avenida del Puerto, 24", "city": "46021 Valencia"},
     "date_order": "23/10/2026", "order_line": [
         {"name": "Mantenimiento mensual", "product_uom_qty": 1, "price_unit": "320,00", "price_subtotal": "320,00"}],
     "amount_untaxed": "320,00", "amount_tax": "67,20", "amount_total": "387,20"},
]


def parse_xml(source):
    if len(source.encode()) > 500_000:
        raise ValueError("La plantilla supera el límite de 500 KB.")
    if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise ValueError("No se permiten DTD ni entidades XML.")
    try:
        return etree.fromstring(source.encode(), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"XML inválido: {exc.msg} (línea {exc.lineno}).") from exc


def annotate(source):
    root = parse_xml(source)
    for index, node in enumerate(node for node in root.iter() if isinstance(node.tag, str)):


        if node.tag not in ("t", "template", "odoo", "data", "xpath"):
            node.set("data-editor-node", str(index))
    return etree.tostring(root, encoding="unicode")


def expression(source, context):
    """Evaluate the supported names, data attributes, constants and negation."""
    def visit(node):
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            if node.id not in context:
                raise ValueError(f"Variable no disponible en demo: {node.id}")
            return context[node.id]
        if isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
            value = visit(node.value)
            if isinstance(value, dict) and node.attr in value:
                return value[node.attr]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [visit(item) for item in node.elts]
        if isinstance(node, ast.Dict) and not node.keys:
            return {}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not visit(node.operand)
        raise ValueError(f"Expresión no compatible con la demo: {source}. Usa Odoo para QWeb completo.")
    try:
        return visit(ast.parse(source, mode="eval").body)
    except SyntaxError as exc:
        raise ValueError(f"Expresión inválida: {source}") from exc


def render(source, record_id):
    record = next((row for row in RECORDS if row["id"] == record_id), None)
    if not record:
        raise ValueError("Selecciona un registro de ejemplo válido.")
    root = parse_xml(annotate(source))
    budget = [0]

    def node_html(node, context):
        budget[0] += 1
        if budget[0] > 20_000:
            raise ValueError("La demo supera el límite de elementos renderizados.")
        if not isinstance(node.tag, str):
            return ""
        supported = {"t-if", "t-field", "t-out", "t-esc", "t-name", "t-as", "t-foreach"}
        for name in node.attrib:
            if name.startswith("t-") and name not in supported and not name.startswith("t-att-"):
                raise ValueError(f"{name} necesita el motor real de Odoo; no se interpreta en demo.")
        if "t-foreach" in node.attrib:
            sequence = expression(node.get("t-foreach"), context)
            if not isinstance(sequence, (list, tuple)):
                raise ValueError("El bucle de la demo necesita una lista de registros.")
            clone = copy.deepcopy(node)
            clone.attrib.pop("t-foreach")
            alias = clone.attrib.pop("t-as", "item")
            return "".join(node_html(clone, {**context, alias: item, alias + "_index": i}) for i, item in enumerate(sequence))
        if "t-if" in node.attrib and not expression(node.get("t-if"), context):
            return ""
        for directive in ("t-call", "t-set", "t-raw", "t-else", "t-elif"):
            if directive in node.attrib:
                raise ValueError(f"{directive} necesita el motor real de Odoo; no se interpreta en demo.")
        value_expr = node.get("t-field") or node.get("t-out") or node.get("t-esc")
        if value_expr:
            content = html.escape(str(expression(value_expr, context)))
        else:
            content = html.escape(node.text or "") + "".join(node_html(child, context) + html.escape(child.tail or "") for child in node)
        if node.tag in ("t", "template", "odoo"):
            return content
        attrs = {}
        for key, value in node.attrib.items():
            if key.startswith("t-att-"):
                attrs[key[6:]] = str(expression(value, context))
            elif key.startswith("t-"):
                if key not in ("t-if", "t-field", "t-out", "t-esc", "t-name", "t-as"):
                    raise ValueError(f"{key} no está implementado en demo. Conecta Odoo para renderizarlo.")
            else:
                attrs[key] = value
        attributes = "".join(f' {key}="{html.escape(value, quote=True)}"' for key, value in attrs.items())
        if node.tag in ("br", "hr", "img", "input", "meta", "link"):
            return f"<{node.tag}{attributes}>"
        return f"<{node.tag}{attributes}>{content}</{node.tag}>"

    return node_html(root, {"o": record, "doc": record, "docs": [record]})


def preview(source, record_id, placeholders=True):
    try:
        return {"html": render(source, record_id), "warnings": [], "placeholder_mode": False}
    except ValueError:
        if not placeholders:
            raise
        from types import SimpleNamespace
        from .qweb_support import PlaceholderTemplates

        def model(fields, relations=None):
            return SimpleNamespace(_fields={name: SimpleNamespace(comodel_name=(relations or {}).get(name)) for name in fields})

        env = {"sale.order": model(RECORDS[0], {"partner_id": "res.partner", "order_line": "sale.order.line"}),
               "res.partner": model(RECORDS[0]["partner_id"]), "sale.order.line": model(RECORDS[0]["order_line"][0])}
        helper = PlaceholderTemplates(env, "sale.order")
        tree = helper.transform(parse_xml(source), "demo.sale_order")
        if not helper.warnings:
            raise
        return {"html": render(etree.tostring(tree, encoding="unicode"), record_id),
                "warnings": helper.warnings, "placeholder_mode": True}
