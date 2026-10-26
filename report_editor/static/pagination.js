/**
 * Paginate rendered report content into A4 sheets using browser fragmentation.
 */
const A4 = {width: 210 * 96 / 25.4, height: 297 * 96 / 25.4, gap: 24};
class ReportPages {
  constructor(doc, paper = {}) {
    this.doc = doc;
    this.original = doc.createElement('div');
    this.original.append(...Array.from(doc.body.childNodes).map(node => node.cloneNode(true)));
    this.headers = [...this.original.querySelectorAll('.header')].filter(node => !node.closest('.page'));
    this.footers = [...this.original.querySelectorAll('.footer')].filter(node => !node.closest('.page'));
    [...this.headers, ...this.footers].forEach(node => node.remove());
    this.margins = {};
    for (const side of ['top', 'right', 'bottom', 'left']) {
      const override = doc.querySelector(`[data-report-margin-${side}]`)?.getAttribute(`data-report-margin-${side}`);
      const mm = Number(override ?? paper.margins?.[side] ?? 0);
      this.margins[side] = Math.max(0, Math.min(side === 'left' || side === 'right' ? 70 : 100, Number.isFinite(mm) ? mm : 0)) * 96 / 25.4;
    }
    this.contentWidth = A4.width - this.margins.left - this.margins.right;
    this.contentHeight = A4.height - this.margins.top - this.margins.bottom;
    this.style = doc.createElement('style');
    this.style.textContent = `
      html,body{margin:0!important;padding:0!important;width:${A4.width}px!important;min-height:0!important;background:transparent!important;overflow:hidden!important}
      .editor-sheet{position:relative!important;box-sizing:border-box!important;width:${A4.width}px!important;height:${A4.height}px!important;margin:0 0 ${A4.gap}px!important;background:white!important;overflow:hidden!important;box-shadow:0 2px 9px #212b4720}
      .editor-sheet:last-child{margin-bottom:0!important}
      .editor-page-viewport{position:absolute!important;left:${this.margins.left}px!important;top:${this.margins.top}px!important;width:${this.contentWidth}px!important;height:${this.contentHeight}px!important;overflow:hidden!important}
      .editor-flow{position:relative!important;width:${this.contentWidth}px!important;height:${this.contentHeight}px!important;column-width:${this.contentWidth}px!important;column-gap:0!important;column-fill:auto!important;column-count:auto!important;overflow:visible!important;box-sizing:border-box!important;overflow-wrap:break-word}
      .editor-flow .container{max-width:100%!important}
      .editor-flow div.page{min-height:0!important;page-break-after:auto;break-after:column}
      .editor-flow div.page:last-child{break-after:auto}
      .editor-flow tr,.editor-flow img,.editor-flow h1,.editor-flow h2,.editor-flow h3{break-inside:avoid}
      .editor-flow [style*="page-break-before: always"],.editor-flow [style*="page-break-before:always"]{break-before:column!important}
      .editor-flow [style*="page-break-after: always"],.editor-flow [style*="page-break-after:always"]{break-after:column!important}
      .editor-header,.editor-footer{position:absolute!important;left:${this.margins.left}px;right:${this.margins.right}px;overflow:hidden}
      .editor-header{top:0;height:${this.margins.top}px}.editor-footer{bottom:0;height:${this.margins.bottom}px}
      .editor-header>.header,.editor-footer>.footer{position:static!important;width:100%!important}
      .editor-sheet-number{position:absolute;bottom:4px;right:9px;font:9px Arial,sans-serif;color:#a4a9b2;pointer-events:none}
    `;
    doc.head.append(this.style);
  }
  layout() {
    const doc = this.doc;
    const flow = doc.createElement('div');
    flow.className = 'editor-flow';
    flow.append(...Array.from(this.original.childNodes).map(node => node.cloneNode(true)));
    const first = this.sheet(flow, 0);
    doc.body.replaceChildren(first);
    const count = Math.max(1, Math.ceil((flow.scrollWidth - 1) / this.contentWidth));
    for (let index = 1; index < count; index++) doc.body.append(this.sheet(flow.cloneNode(true), index));
    doc.querySelectorAll('.editor-sheet').forEach((sheet, index) => {
      sheet.setAttribute('aria-label', `Página ${index + 1} de ${count}`);
      sheet.querySelectorAll('span.page').forEach(node => node.textContent = index + 1);
      sheet.querySelectorAll('span.topage').forEach(node => node.textContent = count);
      const label = doc.createElement('span'); label.className = 'editor-sheet-number'; label.textContent = `${index + 1} / ${count}`; sheet.append(label);
    });
    this.count = count;
    return count;
  }
  sheet(flow, index) {
    const doc = this.doc, sheet = doc.createElement('section'), viewport = doc.createElement('div');
    sheet.className = 'editor-sheet'; viewport.className = 'editor-page-viewport';
    flow.style.left = `${-index * this.contentWidth}px`;
    viewport.append(flow); sheet.append(viewport);
    for (const [name, nodes] of [['header', this.headers], ['footer', this.footers]]) {
      if (!nodes.length) continue;
      const holder = doc.createElement('div'); holder.className = `editor-${name}`;
      holder.append(...nodes.map(node => node.cloneNode(true))); sheet.append(holder);
    }
    return sheet;
  }
}
