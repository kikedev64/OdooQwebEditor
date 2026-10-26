"""Run against a local demo server: python tests/browser_smoke.py."""
from playwright.sync_api import expect, sync_playwright


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    def choose(page, kind, query):
        page.locator(f"#{kind}-search").click()
        page.locator(f"#{kind}-search").fill(query)
        option = page.locator(f"#{kind}-results").get_by_role("option").first
        expect(option).to_be_visible()
        option.click()

    def select_example(page):
        page.locator("#model-search").click()
        page.locator("#model-search").fill("sale.order")
        expect(page.locator("#model-results").get_by_role("option").first).to_be_visible()
        page.locator("#model-search").press("ArrowDown")
        page.locator("#model-search").press("Enter")
        choose(page, "report", "demo.sale_order")
        choose(page, "record", "#1")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1512, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(8000)
        try:
            page.goto(args.url)
            frame = page.frame_locator("#preview")
            expect(page.locator("#report-search")).to_be_disabled()
            expect(page.locator("#record-search")).to_be_disabled()
            expect(page.locator(".breadcrumb")).to_have_count(0)
            select_example(page)
            expect(frame.locator("h1")).to_have_text("Presupuesto")
            choose(page, "record", "#2")
            expect(frame.locator("strong").first).to_have_text("Taller del Mar")

            clean = page.locator("#source").input_value()
            page.locator("#source").fill(clean.replace('t-field="o.name"', 't-field="o.missing_reference"'))
            expect(page.locator("#placeholder-warning")).to_be_visible()
            expect(frame.locator("[data-editor-placeholder]")).to_contain_text("[sale.order.missing_reference]")
            page.locator("#placeholders").uncheck()
            expect(page.locator("#error")).to_be_visible()
            page.locator("#placeholders").check()
            expect(page.locator("#error")).to_be_hidden()
            page.locator("#source").fill(clean)
            expect(page.locator("#placeholder-warning")).to_be_hidden()

            original = page.locator("#source").input_value()
            page.locator("#source").fill(original.replace("o.", "doc."))
            page.locator("#fields .field").filter(has_text="Referencia").first.click()
            expect(frame.locator('span', has_text="S00043")).to_have_count(1)
            assert 't-field="doc.name"' in page.locator("#source").input_value()
            page.locator("#source").fill(original)
            expect(frame.locator('span', has_text="S00043")).to_have_count(0)

            frame.locator("h1").click()
            page.locator("#element-text").fill("Oferta comercial")
            page.locator("#element-text").press("Tab")
            expect(frame.locator("h1")).to_have_text("Oferta comercial")
            page.locator("#element-color").fill("#ff0000")
            page.locator("#element-color").press("Tab")
            expect(frame.locator("h1")).to_have_css("color", "rgb(255, 0, 0)")

            page.get_by_role("button", name="Título", exact=False).first.drag_to(frame.locator("h1"))
            expect(frame.locator("h2", has_text="Nuevo título")).to_have_count(1)
            frame.locator("h2", has_text="NORTHWIND").drag_to(frame.locator("h1"))
            expect(frame.locator("h1 + h2")).to_have_text("NORTHWIND")
            page.locator("#undo").click()
            expect(frame.locator("h1 + h2")).to_have_text("Nuevo título")
            page.locator("#redo").click()
            expect(frame.locator("h1 + h2")).to_have_text("NORTHWIND")

            with page.expect_response(lambda response: response.url.endswith("/api/save")) as exported:
                page.locator("#save-button").click()
            xml = exported.value.json()["xml"]
            expect(page.locator("#toast")).to_contain_text("XML guardado")
            page.reload()
            select_example(page)
            expect(frame.locator("h1")).to_have_text("Oferta comercial")
            page.locator("#source").fill("<t><p>XML incorrecto</t>")
            expect(page.locator("#error")).to_be_visible()
            expect(frame.locator("h1")).to_have_text("Oferta comercial")

            for width, height in [(800, 1100), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(150)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, errors
            print("OK: registros, edición visual, estilos, arrastre, deshacer/rehacer, exportar, errores y responsive.")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
