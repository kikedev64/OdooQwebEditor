"""Embed report resources while the draft's Odoo transaction is still alive."""
import base64
import mimetypes
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit


def embed_report_resources(document, resolver, base_url=""):
    """Inline local CSS, fonts and images without relying on browser credentials."""
    from lxml import html

    root = html.document_fromstring(document)
    warnings, cache = [], {}
    origin = urlsplit(base_url).netloc

    def local(url):
        parsed = urlsplit(url)
        return (not parsed.scheme and not parsed.netloc) or (
            parsed.scheme in ("", "http", "https") and parsed.netloc == origin)

    def load(url):
        if url not in cache:
            cache[url] = resolver(url)
        return cache[url]

    def data_url(url, parent="/"):
        if not url or url.startswith(("data:", "#")):
            return url
        absolute = urljoin(parent, url)
        if not local(absolute):
            return absolute
        try:
            content, mime = load(absolute)
            fragment = urlsplit(absolute).fragment
            return "data:" + mime + ";base64," + base64.b64encode(content).decode() + ("#" + fragment if fragment else "")
        except (ValueError, OSError, KeyError) as exc:
            warnings.append({"url": absolute, "message": str(exc)[:200]})
            return absolute

    def css(text, parent="/", seen=()):
        def imported(match):
            url = urljoin(parent, match.group(1))
            if not local(url) or url in seen:
                return match.group(0)
            try:
                content, _ = load(url)
                return css(content.decode("utf-8"), url, (*seen, url))
            except (ValueError, OSError, KeyError) as exc:
                warnings.append({"url": url, "message": str(exc)[:200]})
                return match.group(0)
        text = re.sub(r'@import\s+[\'"]([^\'"]+)[\'"]\s*;', imported, text, flags=re.I)
        def replace(match):
            url = match.group(2).strip()
            absolute = urljoin(parent, url)
            if absolute.split("?", 1)[0].endswith(".css") and local(absolute) and absolute not in seen:
                try:
                    content, _ = load(absolute)
                    embedded = css(content.decode("utf-8"), absolute, (*seen, absolute))
                    return 'url("data:text/css;base64,' + base64.b64encode(embedded.encode()).decode() + '")'
                except (ValueError, OSError, KeyError):
                    pass
            return 'url("' + data_url(url, parent) + '")'
        return re.sub(r'url\(\s*([\'"]?)(.*?)\1\s*\)', replace, text, flags=re.I)

    for node in root.xpath('//link[contains(concat(" ", normalize-space(@rel), " "), " stylesheet ")]'):
        url = node.get("href", "")
        if not url or not local(url):
            continue
        try:
            content, _ = load(url)
            node.tag = "style"
            node.attrib.pop("href", None)
            node.attrib.pop("rel", None)
            node.attrib.pop("integrity", None)
            node.text = css(content.decode("utf-8"), url)
        except (ValueError, OSError, KeyError) as exc:
            warnings.append({"url": url, "message": str(exc)[:200]})
    for node in root.xpath('//style'):
        node.text = css(node.text or "")
    for node in root.iter():
        if node.get("style"):
            node.set("style", css(node.get("style")))
        for attr in ("src", "poster", "background"):
            if node.get(attr) and node.tag not in ("script", "iframe"):
                node.set(attr, data_url(node.get(attr)))
        if node.get("srcset") and not node.get("srcset").lstrip().startswith("data:"):
            candidates = []
            for candidate in node.get("srcset").split(","):
                parts = candidate.strip().split()
                if parts:
                    candidates.append(" ".join([data_url(parts[0]), *parts[1:]]))
            node.set("srcset", ", ".join(candidates))
    for node in list(root.xpath('//style')):
        text = node.text or ""
        if len(text) < 500_000:
            continue
        depth, start, chunks, chunk = 0, 0, [], ""
        tokens = r'/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{};]'
        for match in re.finditer(tokens, text):
            token = match.group()
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
            if depth == 0 and token in ("}", ";"):
                rule = text[start:match.end()]
                if chunk and len(chunk) + len(rule) > 500_000:
                    chunks.append(chunk)
                    chunk = ""
                chunk += rule
                start = match.end()
        chunks.append(chunk + text[start:])
        parent, offset = node.getparent(), node.getparent().index(node)
        parent.remove(node)
        for index, chunk in enumerate(chunks):
            style = html.Element('style', attrib=dict(node.attrib))
            style.text = chunk
            style.tail = node.tail if index == len(chunks) - 1 else None
            parent.insert(offset + index, style)
    unique = {(item['url'], item['message']): item for item in warnings}
    doctype = root.getroottree().docinfo.doctype or None
    return html.tostring(root, encoding="unicode", doctype=doctype), list(unique.values())


def odoo_report_resource(env, url):
    """Read only report resource routes through the selected Odoo environment."""
    import os
    from odoo.modules.module import get_module_resource

    parsed = urlsplit(url)
    path = unquote(parsed.path)
    query = parse_qs(parsed.query)
    parts = path.strip("/").split("/")
    if ".." in parts or "\\" in path or "\x00" in path:
        raise ValueError("Ruta de recurso no válida.")
    if parts[:2] == ["report", "barcode"]:
        kind = parts[2] if len(parts) > 2 else query.get("barcode_type", query.get("type", ["Code128"]))[0]
        value = "/".join(parts[3:]) if len(parts) > 3 else query.get("value", [""])[0]
        options = {key: values[0] for key, values in query.items() if key in (
            "width", "height", "humanreadable", "quiet", "mask", "barLevel")}
        return env["ir.actions.report"].barcode(kind, value, **options), "image/png"
    if len(parts) > 2 and parts[1] == "static":
        static_root = get_module_resource(parts[0], "static")
        filename = get_module_resource(parts[0], *parts[1:])
        if not filename or not static_root or os.path.commonpath([os.path.realpath(filename), os.path.realpath(static_root)]) != os.path.realpath(static_root):
            raise ValueError("Recurso estático no encontrado.")
        with open(filename, "rb") as stream:
            return stream.read(), mimetypes.guess_type(filename)[0] or "application/octet-stream"
    attachment = env["ir.attachment"].search([("url", "=", parsed.path)], limit=1)
    if attachment:
        return base64.b64decode(attachment.datas or b""), attachment.mimetype or "application/octet-stream"
    if parts[:2] not in (["web", "image"], ["web", "content"]):
        raise ValueError("No se encontró el recurso del informe.")
    tail = parts[2:]
    model = query.get("model", [None])[0]
    record_id = query.get("id", [None])[0]
    field = query.get("field", [None])[0]
    if tail:
        if tail[0].split("-", 1)[0].isdigit():
            model, record_id, field = "ir.attachment", tail[0].split("-", 1)[0], "datas"
        elif len(tail) >= 3 and tail[1].isdigit():
            model, record_id, field = tail[:3]
        else:
            record = env.ref(tail[0], raise_if_not_found=False)
            if not record:
                raise ValueError("La imagen no existe en esta base de datos.")
            model, record_id = record._name, record.id
            field = tail[1] if len(tail) > 1 else "datas"
    if not model or not record_id:
        raise ValueError("Referencia de imagen incompleta.")
    record = env[model].browse(int(record_id)).exists()
    field = field or "datas"
    if not record or field not in record._fields or record._fields[field].type != "binary":
        raise ValueError("El campo de imagen no existe.")
    value = record.with_context(bin_size=False)[field]
    if not value:
        raise ValueError("El registro no contiene una imagen.")
    content = base64.b64decode(value)
    mime = record.mimetype if model == "ir.attachment" else None
    if not mime:
        from odoo.tools.mimetypes import guess_mimetype
        mime = guess_mimetype(content)
    return content, mime or "application/octet-stream"
