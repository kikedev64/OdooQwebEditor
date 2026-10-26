import ast
from types import SimpleNamespace

from lxml import etree

from report_editor.qweb_support import PlaceholderTemplates, missing_field_details, missing_field_token, resolve_template_view, product_label_preview_data
from report_editor.qweb_support import operation_error_details


class FakeModel:
    def __init__(self, fields):
        self._fields = {name: SimpleNamespace(comodel_name=relation) for name, relation in fields.items()}

    def sudo(self):
        return self


def environment():
    return {
        "sale.order": FakeModel({"name": None, "partner_id": "res.partner", "order_line": "sale.order.line", "company_id": "res.company"}),
        "sale.order.line": FakeModel({"name": None, "price_unit": None}),
        "res.partner": FakeModel({"name": None}),
        "res.company": FakeModel({"name": None}),
        "res.users": FakeModel({"name": None}),
    }


def test_missing_field_placeholder_preserves_original_xml_and_marker():
    original = etree.fromstring(b'<t><p t-field="o.missing" t-options="{\'widget\': \'monetary\'}" data-editor-node="4"/></t>')
    before = etree.tostring(original)
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform(original, "sale.document")
    node = tree.find("p")
    assert ast.literal_eval(node.get("t-esc")) == "[sale.order.missing]"
    assert "t-field" not in node.attrib and "t-options" not in node.attrib
    assert node.get("data-editor-node") == "4"
    assert helper.warnings[0]["field"] == "sale.order.missing"
    assert etree.tostring(original) == before


def test_valid_fields_methods_and_widgets_are_untouched():
    source = '<t><p t-field="o.name"/><p t-field="o.partner_id.name"/><p t-out="o.sudo().name"/></t>'
    helper = PlaceholderTemplates(environment(), "sale.order")
    result = helper.transform(source, "sale.document")
    assert not helper.warnings
    assert etree.tostring(result, encoding="unicode") == source


def test_related_model_and_company_placeholders():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><p t-field="o.partner_id.vat"/><p t-out="res_company.logo_custom"/></t>', "layout")
    assert ast.literal_eval(tree[0].get("t-esc")) == "[res.partner.vat]"
    assert ast.literal_eval(tree[1].get("t-out")) == "[res.company.logo_custom]"


def test_loop_inference_and_missing_collection_sample_row():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><tr t-foreach="doc.order_line" t-as="line"><td t-field="line.name"/><td t-field="line.custom_ref"/></tr><div t-foreach="o.custom_lines" t-as="item"><p t-field="item.name"/></div></t>', "sale.document")
    assert tree[0][0].get("t-field") == "line.name"
    assert ast.literal_eval(tree[0][1].get("t-esc")) == "[sale.order.line.custom_ref]"
    assert ast.literal_eval(tree[1].get("t-foreach")) == [{}]
    assert ast.literal_eval(tree[1][0].get("t-esc")) == "[sale.order.custom_lines.name]"


def test_set_alias_propagates_to_following_siblings():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><t t-set="customer" t-value="o.partner_id"/><p t-field="customer.custom_ref"/></t>', "sale.document")
    assert ast.literal_eval(tree[1].get("t-esc")) == "[res.partner.custom_ref]"


def test_placeholder_conditions_arithmetic_and_unicode_offsets():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><div t-if="o.optional"><span t-out="o.optional"/></div><p t-out="o.amount_missing * 3"/><p t-out="\'Total €: \' + o.text_missing"/></t>', "sale.document")
    assert tree[0].get("t-if") == "True"
    assert tree[1].get("t-out") == "0 * 3"
    assert tree[2].get("t-out") == "'Total €: ' + '[sale.order.text_missing]'"


def test_missing_model_method_is_not_faked():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><p t-out="o.missing_method()"/></t>', "sale.document")
    assert tree[0].get("t-out") == "o.missing_method()"
    assert not helper.warnings


def test_placeholders_do_not_pass_wrong_types_into_html_or_binary_helpers():
    helper = PlaceholderTemplates(environment(), "sale.order")
    tree = helper.transform('<t><p t-if="not is_html_empty(doc.missing_note)"/><img t-if="doc.missing_image" t-att-src="image_data_uri(doc.missing_image)"/><t t-foreach="sorted(doc.missing_lines)" t-as="line"/></t>', "report")
    assert tree[0].get("t-if") == "True"
    assert tree[1].get("t-if") == "True"
    assert tree[1].get("t-att-src") == "''"
    assert tree[2].get("t-foreach") == "[{}]"


def test_does_not_execute_expressions_while_transforming():
    helper = PlaceholderTemplates(environment(), "sale.order")
    source = '<t><p t-out="__import__(\'os\').getcwd()"/></t>'
    tree = helper.transform(source, "sale.document")
    assert tree[0].get("t-out") == "__import__('os').getcwd()"
    assert not helper.warnings


def test_new_template_view_api_is_preferred():
    view = SimpleNamespace(exists=lambda: "result")

    class ModernViews:
        def _get_template_view(self, reference):
            assert reference == "sale.document"
            return view

    assert resolve_template_view({"ir.ui.view": ModernViews()}, "sale.document") == "result"


def test_legacy_template_view_api():
    class LegacyViews:
        def get_view_id(self, reference):
            return 5

        def browse(self, ident):
            assert ident == 5
            return SimpleNamespace(exists=lambda: "legacy")

    assert resolve_template_view({"ir.ui.view": LegacyViews()}, "sale.document") == "legacy"


def test_internal_missing_api_is_never_classified_as_business_field():
    assert missing_field_details(AttributeError("'ir.ui.view' object has no attribute 'get_view_id'")) is None
    assert missing_field_details(AttributeError("'sale.order' object has no attribute '_render_custom'")) is None
    assert missing_field_details(AttributeError("'sale.order' object has no attribute 'compute_custom'\nNode: <t t-out=\"o.compute_custom()\"/>")) is None
    assert missing_field_details(AttributeError("'repair.order' object has no attribute 'order_ref'"), "list_templates") is None
    assert missing_field_details(AttributeError("'repair.order' object has no attribute 'order_ref'"))["field"] == "order_ref"


def test_widget_record_scope_uses_actual_related_model_and_does_not_leak():
    env = environment()
    env["res.partner"]._name = "res.partner"
    helper = PlaceholderTemplates(env, "sale.order")
    source = '<t><p t-field="object.name"/><p t-field="object.custom_code"/></t>'
    with helper.bind({"object": env["res.partner"]}):
        tree = helper.transform(source, "base.contact")
    assert tree[0].get("t-field") == "object.name"
    assert ast.literal_eval(tree[1].get("t-esc")) == "[res.partner.custom_code]"
    unbound = helper.transform(source, "other.template")
    assert unbound[1].get("t-field") == "object.custom_code"
    assert not helper.scopes


def test_only_fields_which_actually_failed_are_replaced():
    helper = PlaceholderTemplates(environment(), "sale.order", allowed={"sale.order.missing"})
    tree = helper.transform('<t><p t-field="o.missing"/><p t-field="o.other_missing"/><p t-field="o.partner_id.custom_ref"/></t>', "sale.document")
    assert tree[0].get("t-esc")
    assert tree[1].get("t-field") == "o.other_missing"
    assert tree[2].get("t-field") == "o.partner_id.custom_ref"
    assert len(helper.warnings) == 1


def test_failed_node_identifies_alias_from_method_returned_recordset():
    helper = PlaceholderTemplates(environment(), 'sale.order', allowed={'sale.order.line.start_date'})
    source = '''<t><t t-set="lines" t-value="doc._get_order_lines_to_report()"/><p t-foreach="lines" t-as="line"><span t-esc="line.start_date.strftime('%d/%m/%Y')"/><span t-field="line.name"/></p></t>'''
    failure = AttributeError("'sale.order.line' object has no attribute 'start_date'\nTemplate: sale.document\nNode: <span t-esc=\"line.start_date.strftime(\\'%d/%m/%Y\\')\"/>")
    helper.record_failure(failure)
    tree = helper.transform(source, 'sale.document')
    assert ast.literal_eval(tree[1][0].get('t-esc')) == '[sale.order.line.start_date]'
    assert tree[1][1].get('t-field') == 'line.name'
    unrelated = helper.transform('<t><span t-field="line.start_date"/></t>', 'another.document')
    assert unrelated[0].get('t-field') == 'line.start_date'


def test_orm_keyerror_can_be_replaced_but_missing_context_variable_cannot():
    try:
        try:
            raise KeyError("custom_code")
        except KeyError as exc:
            raise ValueError('Element: <span t-field="doc.custom_code"/>') from exc
    except ValueError as exc:
        assert missing_field_token(exc) == "*.custom_code"
    assert missing_field_token(KeyError("tax_totals")) is None


def test_unbound_request_proxy_is_ignored_during_scope_binding():
    class Unbound:
        def __getattr__(self, name):
            raise RuntimeError("object unbound")

    helper = PlaceholderTemplates(environment(), "sale.order")
    with helper.bind({"request": Unbound()}):
        assert helper.initial_scope()["doc"] == "sale.order"


def test_product_labels_prepare_real_wizard_data_without_creating_records():
    class Labels:
        id = 'memory-only-id'

        def new(self, values):
            assert values == {'print_format': '4x12', 'custom_quantity': 1, 'product_tmpl_ids': [(6, 0, [42])]}
            return self

        def _prepare_report_data(self):
            return 'product.label', {'quantity_by_product': {42: 1}, 'layout_wizard': 'memory-only-id'}

    env = {'product.label.layout': Labels()}
    record = SimpleNamespace(_name='product.template', ids=[42])
    data = product_label_preview_data(env, 'product.report_producttemplatelabel4x12noprice', record)
    assert data == {'quantity_by_product': {'42': 1}, 'layout_wizard': ['memory-only-id']}
    assert product_label_preview_data(env, 'sale.report_saleorder', record) is None


def test_schema_and_template_errors_keep_trace_out_of_friendly_message():
    message, diagnostic = operation_error_details(ValueError('column res_partner.custom_flag does not exist\nLINE 1: SELECT ...'))
    assert 'res_partner.custom_flag' in message
    assert 'SELECT' not in message
    assert diagnostic['kind'] == 'schema_error'
    message, diagnostic = operation_error_details(ValueError("Error while render the template\nAttributeError: 'account.move' object has no attribute 'partner_banks_to_show'\nTemplate: account.document\nNode: <t/>"))
    assert 'partner_banks_to_show' in message and 'account.document' in message
    assert 'Node:' not in message and 'Node:' in diagnostic['trace']
    assert diagnostic['kind'] == 'template_error'
