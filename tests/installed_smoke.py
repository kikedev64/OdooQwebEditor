"""Verify the installed CLI and HTTP API using only Python's standard library."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command', default='odoo-report-editor')
    args = parser.parse_args()
    executable = shutil.which(args.command)
    if not executable:
        raise SystemExit('The editor command is not installed or is missing from PATH')
    executable = str(Path(executable).resolve())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='qweb-installed-') as directory:
        with tempfile.TemporaryFile(mode='w+') as log:
            process = subprocess.Popen([executable, '--demo', '--no-browser', '--port', str(port)], cwd=directory, stdout=log, stderr=subprocess.STDOUT)
            try:
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                base = f'http://127.0.0.1:{port}'

                def request(path, data=None):
                    body = None if data is None else json.dumps(data).encode()
                    req = urllib.request.Request(base + path, data=body, headers={'Content-Type': 'application/json', 'X-Editor-Request': '1'})
                    with opener.open(req, timeout=5) as response:
                        return response.read()

                deadline = time.monotonic() + 20
                while True:
                    try:
                        status = json.loads(request('/api/status'))
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise AssertionError('Installed editor did not start:\n' + log.read())
                        time.sleep(0.1)
                assert status['mode'] == 'demo'
                assert request('/').startswith(b'<!doctype html>')
                for resource in ('app.js', 'style.css', 'pagination.js', 'source-map.js', 'placeholder.svg'):
                    assert request('/static/' + resource)
                template = json.loads(request('/api/templates/1'))
                preview = json.loads(request('/api/preview', {'template_id': 1, 'record_id': 1, 'source': template['source']}))
                assert 'data-editor-node=' in preview['html'] and 'Presupuesto' in preview['html']
                saved = json.loads(request('/api/save', {'template_id': 1, 'source': template['source'], 'revision': template['revision']}))
                exported = Path(saved['path'])
                assert exported.parent == Path(directory) / 'report_editor_exports'
                assert exported.is_file() and '<odoo>' in exported.read_text()
                assert 'data-editor-node' not in exported.read_text()
                print('OK: installed command, demo startup, static assets, preview and export relative to the caller directory')
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
