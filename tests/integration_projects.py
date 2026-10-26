"""Read-only integration audit against already running local Odoo containers.

Run manually: python tests/integration_projects.py /path/to/project [...]
Only the exported XML check writes a file, inside a temporary directory.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from lxml import etree

from report_editor.demo import annotate
from report_editor.project import ComposeProject, DockerOdooClient, export_template


def check_draft(client, report, template, record):
    source = template['source']
    root = etree.fromstring(source.encode())
    targets = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' page ')]")
    if not targets:
        return None
    target = targets[0]
    sample = etree.SubElement(target, 'p', {'t-esc': 'docs[0].editor_audit_missing'})
    draft = etree.tostring(root, encoding='unicode')
    args = [template['id'], record['id'], annotate(draft), report['model'], report['id']]
    preview = client.call('preview', *args, {'editor_placeholders': True})
    expected = report['model'] + '.editor_audit_missing'
    assert any(row['field'] == expected for row in preview['warnings']), preview['warnings']
    assert '[' + expected + ']' in preview['html']
    try:
        client.call('preview', *args, {'editor_placeholders': False})
    except ValueError as exc:
        assert 'editor_audit_missing' in str(exc)
    else:
        raise AssertionError('Strict rendering accepted an absent field')
    sample.attrib.clear()
    sample.text = 'EDITOR_AUDIT_DRAFT'
    edited = etree.tostring(root, encoding='unicode')
    result = client.call('preview', template['id'], record['id'], annotate(edited), report['model'], report['id'], {})
    assert 'EDITOR_AUDIT_DRAFT' in result['html']
    assert not any(row['field'] == expected for row in result['warnings'])
    with tempfile.TemporaryDirectory() as directory:
        saved = export_template(directory, template, draft)
        assert 'docs[0].editor_audit_missing' in saved['xml']
        assert '[' + expected + ']' not in saved['xml']
    assert client.call('get_template', template['id'])['source'] == source
    return 'placeholder, strict mode, successive drafts, XML export and unchanged stored architecture'


def audit(directory):
    name = Path(directory).name
    client = DockerOdooClient(ComposeProject.discover(directory))
    results = {'project': name, 'audited_at': datetime.now(timezone.utc).isoformat(), 'sample_policy': 'First template and latest record by ID for each report action', 'reports': [], 'draft_checks': None}
    try:
        results['connection'] = client.inspect()
        if not client.database:
            raise ValueError('Select a database explicitly before running this audit')
        reports = client.call('list_reports')
        print(name, results['connection']['version'], len(reports), 'reports', flush=True)
        for report in reports:
            row = {'key': report['key'], 'model': report['model']}
            results['reports'].append(row)
            try:
                templates = client.call('list_templates', '', report['id'])
                row['templates'] = len(templates)
                fields = client.call('list_fields', report['model'])
                assert fields
                records = client.call('list_records', report['model'], '')
                if not records:
                    row['status'] = 'no_records'
                    continue
                exact = client.call('list_records', report['model'], '#' + str(records[0]['id']))
                assert exact and exact[0]['id'] == records[0]['id']
                if not templates:
                    row['status'] = 'no_templates'
                    continue
                template = client.call('get_template', templates[0]['id'])
                rendered = client.call('preview', template['id'], records[0]['id'], annotate(template['source']), report['model'], report['id'], {})
                assert rendered['html'].strip()
                row.update(status='ok', bytes=len(rendered['html']), warnings=rendered['warnings'])
                assert client.call('get_template', template['id'])['source'] == template['source']
                if not results['draft_checks']:
                    results['draft_checks'] = check_draft(client, report, template, records[0])
            except Exception as exc:
                row.update(status='error', error=str(exc)[:2500])
                if getattr(exc, 'diagnostic', None):
                    row['diagnostic'] = exc.diagnostic
                print(name, report['key'], 'ERROR', str(exc)[:180].replace('\n', ' '), flush=True)
        counts = {status: sum(row['status'] == status for row in results['reports']) for status in ('ok', 'no_records', 'no_templates', 'error')}
        results['counts'] = counts
        print(name, counts, 'draft checks:', bool(results['draft_checks']), flush=True)
    except Exception as exc:
        results['error'] = str(exc)[:2500]
        print(name, 'ERROR', results['error'], flush=True)
    finally:
        client.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('projects', nargs='+')
    parser.add_argument('--output', default='artifacts/integration-results.json')
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(audit, args.projects))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + '\n')
    print('Results:', output)


if __name__ == '__main__':
    main()
