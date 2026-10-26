"""Check A4 fragmentation, source navigation, attribution and collapsible tools."""
import argparse
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8880')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1512, 'height': 1000})
        page.set_default_timeout(10000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(args.url)
            expect(page.locator('#import-button,#import-file')).to_have_count(0)
            page.locator('#about-button').click()
            expect(page.get_by_role('dialog')).to_be_visible()
            expect(page.get_by_role('dialog')).to_contain_text('Desarrollado por kikedev64')
            expect(page.get_by_role('dialog').get_by_role('link')).to_have_attribute('href', 'https://github.com/kikedev64/kikedev64')
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog')).not_to_be_visible()
            width = page.locator('.sidebar').bounding_box()['width']
            page.locator('#toggle-tools').click()
            expect(page.locator('#toggle-tools')).to_have_attribute('aria-expanded', 'false')
            expect(page.locator('#blocks')).not_to_be_visible()
            page.reload()
            expect(page.locator('#toggle-tools')).to_have_attribute('aria-expanded', 'false')
            page.wait_for_timeout(200)
            assert page.locator('.sidebar').bounding_box()['width'] < min(60, width)
            page.locator('#toggle-tools').click()

            def choose(kind, value):
                page.locator(f'#{kind}-search').fill(value)
                option = page.locator(f'#{kind}-results').get_by_role('option').first
                expect(option).to_be_visible()
                option.click()
            choose('model', 'sale.order')
            choose('report', 'demo.sale_order')
            choose('record', '#1')
            frame = page.frame_locator('#preview')
            expect(frame.locator('.editor-sheet')).to_have_count(1)
            frame.locator('h1').click()
            selected = page.locator('#source').evaluate('(editor) => editor.value.slice(editor.selectionStart, editor.selectionEnd)')
            assert selected.startswith('<h1'), selected
            assert 'Línea' in page.locator('#cursor-position').inner_text()
            page.locator('#source').evaluate('''editor => {
                const offset = editor.value.indexOf('<h2'); editor.focus(); editor.setSelectionRange(offset + 2, offset + 2);
                editor.dispatchEvent(new KeyboardEvent('keyup', {key:'ArrowRight', bubbles:true}));
            }''')
            expect(frame.locator('h2', has_text='NORTHWIND')).to_have_attribute('data-editor-selected', '1')

            ranges = page.evaluate('''() => templateRanges(`<t>\n<!-- <fake/> --><![CDATA[<hidden/>]]><div title="a > b"><span\n t-out="o.name"/></div><p>fin</p></t>`)''')
            assert len(ranges) == 4, ranges
            assert ranges[1]['end'] > ranges[2]['end']

            def margins(route):
                response = route.fetch()
                result = response.json()
                result['paper'] = {'margins': {'top': 15, 'right': 12, 'bottom': 15, 'left': 12}}
                route.fulfill(response=response, json=result)
            page.route('**/api/preview', margins)
            paragraphs = '\n'.join(f'<p style="margin:0;height:32px;line-height:32px;">Fila {n:03}</p>' for n in range(70))
            source = '<t><div class="header"><p style="margin:4px">Cabecera de ejemplo</p></div><div class="page" style="font-family:Arial;font-size:14px;">\n<h1>Documento largo</h1>\n' + paragraphs + '\n</div><div class="footer"><p style="margin:4px">Pie · <span class="page"/> / <span class="topage"/></p></div></t>'
            page.locator('#source').fill(source)
            expect(frame.locator('.editor-sheet')).to_have_count(3)
            expect(page.locator('#page-count')).to_have_text('A4 · 3 páginas')
            expect(frame.locator('.editor-header')).to_have_count(3)
            expect(frame.locator('.editor-footer')).to_have_count(3)
            expect(frame.locator('.editor-sheet').last.locator('.editor-footer')).to_contain_text('3 / 3')
            bounds = frame.locator('.editor-sheet').first.evaluate('(node) => ({width:node.offsetWidth,height:node.offsetHeight})')
            assert abs(bounds['width'] - 794) < 2 and abs(bounds['height'] - 1123) < 2, bounds
            margin = frame.locator('.editor-page-viewport').first.evaluate('(node) => ({left:node.offsetLeft, top:node.offsetTop})')
            assert abs(margin['left'] - 12 * 96 / 25.4) < 2 and abs(margin['top'] - 15 * 96 / 25.4) < 2, margin
            page.locator('#source').evaluate('''editor => {
                const offset = editor.value.indexOf('Fila 069'); editor.focus(); editor.setSelectionRange(offset, offset);
                editor.dispatchEvent(new MouseEvent('click', {bubbles:true}));
            }''')
            page.wait_for_timeout(100)
            assert page.locator('#preview-scroll').evaluate('(node) => node.scrollTop') > 500

            visible = frame.locator('.editor-page-viewport').evaluate_all('''viewports => viewports.flatMap(viewport => {
                const bounds = viewport.getBoundingClientRect();
                return [...viewport.querySelectorAll('p')].filter(node => [...node.getClientRects()].some(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 && rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1)).map(node => node.textContent);
            })''')
            assert sorted(visible) == [f'Fila {n:03}' for n in range(70)], visible
            frame.locator('.editor-sheet').last.locator('p', has_text='Fila 069').click()
            selected_offset = page.locator('#source').evaluate('(editor) => editor.selectionStart')
            assert selected_offset == source.rfind('<p', 0, source.index('Fila 069'))
            page.locator('#zoom').select_option('1.25')
            expect(frame.locator('.editor-sheet')).to_have_count(3)
            assert page.locator('#source').input_value() == source

            page.locator('#source').fill('<t><div class="page"><p>Primera hoja</p></div><div class="page"><p>Segunda hoja</p></div></t>')
            expect(frame.locator('.editor-sheet')).to_have_count(2)
            page.locator('#zoom').select_option('fit')
            rows = ''.join(f'<tr><td style="height:35px;padding:5px;">Registro {n:03}</td></tr>' for n in range(65))
            page.locator('#source').fill('<t><div class="page"><table style="width:100%;border-collapse:collapse"><thead><tr><th>Registros</th></tr></thead><tbody>' + rows + '</tbody></table></div></t>')
            expect(frame.locator('.editor-sheet')).to_have_count(3)
            intact_rows = frame.locator('.editor-page-viewport').evaluate_all('''viewports => viewports.flatMap(viewport => {
                const bounds = viewport.getBoundingClientRect();
                return [...viewport.querySelectorAll('tbody tr')].filter(node => [...node.getClientRects()].some(rect => rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1 && rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1)).map(node => node.textContent);
            })''')
            assert sorted(intact_rows) == [f'Registro {n:03}' for n in range(65)], intact_rows
            assert not errors, errors
            print('OK: attribution, import removed, folding, bidirectional XML selection, A4 margins, three pages, complete paragraphs and zoom')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
