"""Browser integration checks for real local projects; no saves or DB writes.

Usage: python tests/browser_projects.py --url http://127.0.0.1:8877
"""
import argparse
from lxml import etree
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--model', default='ir.model')
    parser.add_argument('--report', default='base.report_irmodeloverview')
    args = parser.parse_args()
    expect.set_options(timeout=90000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1512, 'height': 1000})
        page.set_default_timeout(90000)
        errors = []
        misplaced_resources = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: misplaced_resources.append(request.url) if request.url.startswith(args.url + '/web/') else None)
        try:
            page.goto(args.url)
            expect(page.locator('#model-search')).to_be_enabled()
            page.locator('#preview-mode').select_option('html')
            page.locator('#placeholders').check()

            def choose(kind, query):
                page.locator(f'#{kind}-search').click()
                page.locator(f'#{kind}-search').fill(query)
                option = page.locator(f'#{kind}-results').get_by_role('option').first
                expect(option).to_be_visible()
                option.click()

            choose('model', args.model)
            choose('report', args.report)
            response = page.request.get(args.url + '/api/records', params={'model': args.model, 'q': ''}, timeout=90000)
            assert response.ok, response.text()
            record = response.json()[0]
            choose('record', '#' + str(record['id']))
            expect(page.locator('#paper-wrapper')).to_be_visible()
            expect(page.locator('#error')).to_be_hidden()
            frame = page.frame_locator('#preview')
            expect(frame.locator('[data-editor-node]').first).to_be_attached()
            original = page.locator('#source').input_value()
            template_id = page.locator('#template').input_value()
            stored = page.request.get(args.url + '/api/templates/' + template_id).json()['source']

            page.locator('.block').filter(has_text='Texto').click()
            paragraph = frame.locator('p', has_text='Escribe aquí tu texto').last
            expect(paragraph).to_be_visible()
            paragraph.click()
            page.locator('#element-text').fill('EDITOR_BROWSER_CHECK')
            page.locator('#element-text').press('Tab')
            expect(frame.locator('p', has_text='EDITOR_BROWSER_CHECK').last).to_be_visible()
            page.locator('#element-color').fill('#ff0000')
            page.locator('#element-color').press('Tab')
            expect(frame.locator('p', has_text='EDITOR_BROWSER_CHECK').last).to_have_css('color', 'rgb(255, 0, 0)')

            root = etree.fromstring(original.encode())
            pages = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' page ')]")
            targets = pages or root.xpath('//*[@t-foreach="docs"]') or root.xpath('//div')
            assert targets, 'Choose a report with a document container for this check'
            etree.SubElement(targets[0], 'p', {'t-esc': 'docs[0].editor_browser_missing'})
            page.locator('#source').fill(etree.tostring(root, encoding='unicode'))
            expect(page.locator('#placeholder-list')).to_contain_text(args.model + '.editor_browser_missing')
            expect(frame.locator('[data-editor-placeholder]', has_text=args.model + '.editor_browser_missing').first).to_be_attached()
            page.locator('#placeholders').uncheck()
            expect(page.locator('#error')).to_be_visible()
            expect(page.locator('#error-message')).not_to_be_empty()
            page.locator('#placeholders').check()
            expect(page.locator('#error')).to_be_hidden()
            page.locator('#source').fill(original)
            expect(frame.locator('[data-editor-placeholder]', has_text='editor_browser_missing')).to_have_count(0)
            assert page.request.get(args.url + '/api/templates/' + template_id).json()['source'] == stored
            assert not errors, errors
            assert not misplaced_resources, misplaced_resources
            page.locator('#preview-mode').select_option('pdf')
            expect(page.locator('#pdf-preview')).to_be_visible()
            expect(page.locator('#preview-status')).to_have_text('PDF de Odoo actualizado')
            pdf = page.request.get(args.url + page.locator('#pdf-preview').get_attribute('src'))
            assert pdf.ok and pdf.headers['content-type'] == 'application/pdf'
            assert pdf.body().startswith(b'%PDF-')
            print('OK:', args.url, args.report, 'selection, ID search, visual editing, styles, placeholders, strict mode, stored XML unchanged')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
