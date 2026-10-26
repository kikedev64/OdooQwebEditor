"""Validate the Debian archive, its isolated payload and reproducible builds."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def packages(tmp_path_factory):
    if not shutil.which('dpkg-deb'):
        pytest.skip('Debian packaging tools are not installed')
    temporary = tmp_path_factory.mktemp('debian package')
    paths = []
    environment = {**os.environ, 'SOURCE_DATE_EPOCH': '1792627200'}
    for name in ('first build', 'second build'):
        output = temporary / name
        subprocess.run(['bash', str(ROOT / 'build_deb.sh'), str(output)], check=True, capture_output=True, env=environment)
        paths.append(next(output.glob('*.deb')))
    return paths


def test_package_build_is_reproducible_and_handles_output_paths_with_spaces(packages):
    assert hashlib.sha256(packages[0].read_bytes()).digest() == hashlib.sha256(packages[1].read_bytes()).digest()


def test_package_has_only_application_resources_and_documentation(packages):
    data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(packages[0])])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        assert './usr/bin/odoo-report-editor' in names
        assert './usr/share/odoo-report-editor/report_editor/static/pagination.js' in names
        assert './usr/share/man/man1/odoo-report-editor.1.gz' in names
        assert './usr/share/doc/odoo-report-editor/copyright' in names
        assert not any(part in name for name in names for part in ('.venv', '__pycache__', 'report_editor_exports', 'artifacts', '/tests/', '.git/'))
        assert all(member.uid == 0 and member.gid == 0 for member in members)
        launcher = archive.extractfile('./usr/bin/odoo-report-editor').read().decode()
        assert launcher.startswith('#!/usr/bin/python3\n')
        assert '/usr/share/odoo-report-editor' in launcher
        assert 'chdir' not in launcher
        assert archive.getmember('./usr/bin/odoo-report-editor').mode & 0o111 == 0o111


def test_package_declares_system_dependencies_and_has_no_install_hooks(packages):
    fields = subprocess.check_output(['dpkg-deb', '--field', str(packages[0])], text=True)
    assert 'Architecture: all' in fields
    for dependency in ('python3 (>= 3.11)', 'python3-fastapi (>= 0.101)', 'python3-uvicorn (>= 0.27)', 'python3-lxml (>= 5)'):
        assert dependency in fields
    data = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(packages[0])])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        assert {member.name for member in archive.getmembers() if member.isfile()} == {'./control', './md5sums'}
