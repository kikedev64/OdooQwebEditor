/**
 * Map XML element offsets to the element indices used by preview markers.
 * @param {string} source - The complete XML template.
 * @returns {Array<{index: number, start: number, openEnd: number, end: number}>}
 */
function templateRanges(source) {
  const ranges = [], stack = [];
  let offset = 0;
  while ((offset = source.indexOf('<', offset)) !== -1) {
    const start = offset;
    const special = [['<!--', '-->'], ['<![CDATA[', ']]>'], ['<?', '?>']].find(([prefix]) => source.startsWith(prefix, offset));
    if (special) { const end = source.indexOf(special[1], offset + special[0].length); offset = end < 0 ? source.length : end + special[1].length; continue; }
    const match = source.slice(offset).match(/^<(\/?)([\w:.-]+)/);
    if (!match) { offset++; continue; }
    let quote = null;
    offset += match[0].length;
    for (; offset < source.length; offset++) {
      const char = source[offset];
      if (quote) { if (char === quote) quote = null; }
      else if (char === '"' || char === "'") quote = char;
      else if (char === '>') break;
    }
    offset = Math.min(source.length, offset + 1);
    if (match[1]) {
      const node = stack.pop();
      if (node) node.end = offset;
    } else {
      const node = {index: ranges.length, start, openEnd: offset, end: source.length};
      ranges.push(node);
      if (/\/\s*>$/.test(source.slice(start, offset))) node.end = offset;
      else stack.push(node);
    }
  }
  return ranges;
}
