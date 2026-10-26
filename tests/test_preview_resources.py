import base64

from lxml import html

from report_editor.preview_resources import embed_report_resources


def test_embeds_css_relative_fonts_private_images_and_nested_imports():
    resources = {
        '/web/assets/report.css': (b'@import "extra.css"; @font-face{font-family:Report;src:url(../../my/static/font.woff2)} .logo{background:url(/web/image/res.company/1/logo)}', 'text/css'),
        '/web/assets/extra.css': (b'p{color:red}', 'text/css'),
        '/my/static/font.woff2': (b'font-data', 'font/woff2'),
        '/web/image/res.company/1/logo': (b'image-data', 'image/png'),
    }
    output, warnings = embed_report_resources(
        '<html><head><link rel="stylesheet" href="/web/assets/report.css"/></head>'
        '<body><img src="http://odoo.test/web/image/res.company/1/logo"/></body></html>',
        lambda url: resources[url.replace('http://odoo.test', '')], 'http://odoo.test')
    root = html.fromstring(output)
    assert not warnings
    assert not root.xpath('//link')
    assert 'p{color:red}' in output
    assert 'data:font/woff2;base64,' + base64.b64encode(b'font-data').decode() in output
    assert root.xpath('//img/@src') == ['data:image/png;base64,aW1hZ2UtZGF0YQ==']


def test_missing_resources_are_reported_and_external_resources_are_preserved():
    def missing(url):
        raise ValueError('Imagen vacía')
    output, warnings = embed_report_resources(
        '<img src="/web/image/12"/><img src="https://other.test/logo.png"/>', missing, 'http://odoo.test')
    assert len(warnings) == 1
    assert warnings[0]['url'] == '/web/image/12'
    assert 'https://other.test/logo.png' in output


def test_data_urls_and_fragment_urls_are_unchanged():
    output, warnings = embed_report_resources(
        '<p style="filter:url(#shadow)"><img src="data:image/png;base64,aGVsbG8="/></p>',
        lambda url: (_ for _ in ()).throw(AssertionError(url)))
    assert not warnings
    assert 'data:image/png;base64,aGVsbG8=' in output
    assert '#shadow' in output


def test_preserves_standards_mode_and_svg_resource_fragment():
    output, warnings = embed_report_resources(
        '<!DOCTYPE html><html><head><style>p{background:url(/icons.svg#logo)}</style></head><body><p>Logo</p></body></html>',
        lambda url: (b'<svg/>', 'image/svg+xml'))
    assert not warnings
    assert output.startswith('<!DOCTYPE html>')
    assert 'data:image/svg+xml;base64,PHN2Zy8+#logo' in output


def test_large_font_bundles_do_not_truncate_the_document_when_reparsed():
    css = ''.join('@font-face{font-family:f%s;src:url(/font%s.woff2)}' % (n, n) for n in range(22))
    def resolve(url):
        return (css.encode(), 'text/css') if url == '/bundle.css' else (b'x' * 400_000, 'font/woff2')
    output, warnings = embed_report_resources(
        '<html><head><link rel="stylesheet" href="/bundle.css"/></head><body><main>Documento completo</main></body></html>', resolve)
    assert not warnings
    root = html.fromstring(output)
    assert root.xpath('//main/text()') == ['Documento completo']
    assert len(root.xpath('//style')) > 1
