#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf 'Usage: %s [OUTPUT_DIRECTORY]\nBuild the Debian installer without root or network access.\n' "$0"
    exit 0
fi
if (( $# > 1 )); then
    printf 'Expected at most one output directory.\n' >&2
    exit 2
fi
for command in python3 dpkg-deb dpkg gzip install find sort xargs md5sum sha256sum touch du; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Missing build command: %s\n' "$command" >&2
        exit 1
    fi
done
if ! python3 -c 'import tomllib' 2>/dev/null; then
    printf 'Python 3.11 or later is required to build this package.\n' >&2
    exit 1
fi

version="$(python3 -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$project_dir/pyproject.toml")"
dpkg --validate-version "$version"
output_dir="${1:-$project_dir/dist}"
mkdir -p -- "$output_dir"
output_dir="$(cd -- "$output_dir" && pwd)"
stage_dir="$(mktemp -d)"
trap 'rm -rf -- "$stage_dir"' EXIT
package_dir="$stage_dir/odoo-report-editor"
documentation_dir="$package_dir/usr/share/doc/odoo-report-editor"
manual_dir="$package_dir/usr/share/man/man1"
install -d "$package_dir/DEBIAN" "$package_dir/usr/bin" "$package_dir/usr/share/odoo-report-editor" "$documentation_dir" "$manual_dir"
cp -R "$project_dir/report_editor" "$package_dir/usr/share/odoo-report-editor/"
find "$package_dir" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$package_dir" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
install -m 0755 "$project_dir/packaging/odoo-report-editor" "$package_dir/usr/bin/odoo-report-editor"
install -m 0644 "$project_dir/packaging/copyright" "$documentation_dir/copyright"
gzip -n -9 -c "$project_dir/README.md" > "$documentation_dir/README.md.gz"
gzip -n -9 -c "$project_dir/packaging/odoo-report-editor.1" > "$manual_dir/odoo-report-editor.1.gz"
printf 'odoo-report-editor (%s) unstable; urgency=medium\n\n  * Package the local QWeb report editor for terminal use.\n\n -- kikedev64 <kikedev64@users.noreply.github.com>  Thu, 22 Oct 2026 00:00:00 +0000\n' "$version" | gzip -n -9 > "$documentation_dir/changelog.gz"

find "$package_dir/usr" -type d -exec chmod 0755 {} +
find "$package_dir/usr" -type f ! -path "$package_dir/usr/bin/odoo-report-editor" -exec chmod 0644 {} +
installed_size="$(du -sk "$package_dir/usr" | cut -f1)"
cat > "$package_dir/DEBIAN/control" <<CONTROL
Package: odoo-report-editor
Version: $version
Section: devel
Priority: optional
Architecture: all
Maintainer: kikedev64 <kikedev64@users.noreply.github.com>
Installed-Size: $installed_size
Depends: python3 (>= 3.11), python3-fastapi (>= 0.101), python3-uvicorn (>= 0.27), python3-lxml (>= 5)
Suggests: docker-compose-v2 | docker-compose-plugin, xdg-utils
Homepage: https://github.com/kikedev64
Description: Local visual editor for Odoo QWeb reports
 Select a model, report and sample record from a local Docker Compose project.
 Edit XML alongside an interactive, paginated A4 preview and export templates.
 Developed by kikedev64.
CONTROL
(
    cd -- "$package_dir"
    find usr -type f -print0 | LC_ALL=C sort -z | xargs -0 md5sum > DEBIAN/md5sums
)
epoch="${SOURCE_DATE_EPOCH:-$(git -C "$project_dir" log -1 --format=%ct 2>/dev/null || true)}"
epoch="${epoch:-$(date +%s)}"
if [[ ! "$epoch" =~ ^[0-9]+$ ]]; then
    printf 'SOURCE_DATE_EPOCH must be an integer Unix timestamp.\n' >&2
    exit 2
fi
find "$package_dir" -exec touch -h -d "@$epoch" {} +
export SOURCE_DATE_EPOCH="$epoch"
installer="$output_dir/odoo-report-editor_${version}_all.deb"
dpkg-deb --root-owner-group --build "$package_dir" "$installer"
(
    cd -- "$output_dir"
    sha256sum "$(basename -- "$installer")" > "$(basename -- "$installer").sha256"
)
printf '\nInstaller: %s\nInstall: sudo apt install "%s"\n' "$installer" "$installer"
