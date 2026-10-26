"""Discover a local Compose project and talk to its Odoo Python environment."""
import atexit
import json
import queue
import re
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml", "docker_compose.yml", "docker_compose.yaml")


class OdooOperationError(ValueError):
    def __init__(self, message, diagnostic=None):
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass
class ComposeProject:
    directory: Path
    compose: list[str]
    service: str
    startup: list[str]
    url: str

    @classmethod
    def discover(cls, directory, service=None, compose_file=None):
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise ValueError("El directorio del proyecto no existe.")
        path = (directory / compose_file).resolve() if compose_file else next((directory / name for name in COMPOSE_NAMES if (directory / name).is_file()), None)
        if path is None or not path.is_file():
            raise ValueError("No se encontró un Docker Compose en este directorio. Usa --demo para probar el editor sin Odoo.")
        if not shutil.which("docker"):
            raise ValueError("Docker no está instalado o no está disponible en PATH.")
        compose = ["docker", "compose", "--project-directory", str(directory)]

        if compose_file or path.name.startswith("docker_compose"):
            compose += ["-f", str(path)]
        try:
            result = subprocess.run([*compose, "config", "--format", "json"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("No se pudo leer el proyecto con docker compose config.") from exc
        if result.returncode:
            raise ValueError("Docker Compose no pudo resolver la configuración. Ejecuta 'docker compose config' en el proyecto para revisar el error.")
        try:
            services = json.loads(result.stdout)["services"]
        except (ValueError, KeyError) as exc:
            raise ValueError("Docker Compose devolvió una configuración no válida.") from exc
        if service and service not in services:
            raise ValueError(f"El servicio {service} no existe en el Compose.")
        if not service:
            scores = []
            for name, config in services.items():
                hint = f'{config.get("image", "")} {config.get("command", "")} {config.get("build", "")}'.lower()
                score = (60 if name.lower() == "odoo" else 0) + (30 if "odoo" in hint else 0)
                if "proxy" in name.lower() or "proxy" in str(config.get("image", "")).lower():
                    score -= 100
                if score > 0:
                    scores.append((score, name))
            scores.sort(reverse=True)
            if not scores or (len(scores) > 1 and scores[0][0] == scores[1][0]):
                raise ValueError("No se pudo elegir un único servicio Odoo. Indícalo con --service NOMBRE.")
            service = scores[0][1]
        config = services[service]
        command = config.get("command") or []
        tokens = shlex.split(command) if isinstance(command, str) else command
        if tokens and Path(tokens[0]).name in ("sh", "bash") and "-c" in tokens:
            index = tokens.index("-c")
            tokens = shlex.split(tokens[index + 1]) if index + 1 < len(tokens) else []
        startup = []
        flags = {"-c", "--config", "-d", "--database", "--db_host", "--db_port", "--db_user", "--db_password", "--addons-path", "--data-dir", "--db-filter"}
        for index, token in enumerate(tokens):
            if token in flags and index + 1 < len(tokens):
                startup.extend([token, tokens[index + 1]])
            elif "=" in token and token.split("=", 1)[0] in flags:
                startup.append(token)
        url = ""
        ports = config.get("ports", []) + [port for name, other in services.items() if name != service for port in other.get("ports", [])]
        for port in ports:
            if isinstance(port, dict) and int(port.get("target", 0)) == 8069 and port.get("published"):
                url = f'http://127.0.0.1:{port["published"]}'
                break
        return cls(directory, compose, service, startup, url)


class DockerOdooClient:
    """Persistent private Odoo process; stdin/stdout JSON, never a host shell."""
    def __init__(self, project, database=None, python="python3"):
        self.project, self.database, self.python = project, database, python
        self.url, self.version = project.url, ""
        self.lock = threading.Lock()
        self.process = None
        self.messages = queue.Queue()
        self.databases = []
        atexit.register(self.close)

    def close(self):
        process, self.process = self.process, None
        if process:
            try:
                process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
            if process.stdout:
                process.stdout.close()

    def _start(self):
        worker = "\n".join(Path(__file__).with_name(name).read_text() for name in
                           ("preview_resources.py", "qweb_support.py", "docker_worker.py"))
        container = self._running_container()
        self.messages = queue.Queue()
        messages = self.messages
        try:
            self.process = subprocess.Popen(
                ["docker", "exec", "-i", container, self.python, "-u", "-c", worker],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        except OSError as exc:
            raise ValueError("No se pudo ejecutar Python en el contenedor Odoo.") from exc
        process = self.process

        def read():
            for line in process.stdout:
                if line.startswith("QWEB_EDITOR:"):
                    try:
                        messages.put(json.loads(line[len("QWEB_EDITOR:"):]))
                    except ValueError:
                        continue
            messages.put({"ok": False, "error": "El proceso de Odoo ha terminado. Comprueba que el servicio esté arrancado y que Python pueda importar odoo. Puedes usar --python /ruta/al/python."})

        threading.Thread(target=read, daemon=True).start()
        self.process.stdin.write(json.dumps({"startup": self.project.startup}) + "\n")
        self.process.stdin.flush()

    def _running_container(self):


        try:
            for extra in ([], ["--all"]):
                result = subprocess.run(
                    [*self.project.compose, "ps", *extra, "--status", "running", "--quiet", self.project.service],
                    capture_output=True, text=True, timeout=20,
                )
                if result.returncode:
                    raise ValueError("No se pudo consultar el estado de Docker. Comprueba que Docker esté disponible.")
                containers = result.stdout.split()
                if len(containers) == 1:
                    return containers[0]
                if len(containers) > 1:
                    raise ValueError("Hay varios contenedores Odoo en ejecución para este servicio. Deja uno solo para elegir el entorno de forma inequívoca.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("No se pudo consultar el estado de Docker.") from exc
        raise ValueError(f"El servicio {self.project.service} está parado. Arranca el proyecto con Docker Compose y vuelve a abrir el editor.")

    def call(self, method, *args):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            try:
                self.process.stdin.write(json.dumps({"method": method, "args": args, "database": self.database}) + "\n")
                self.process.stdin.flush()
                result = self.messages.get(timeout=90)
            except (OSError, queue.Empty) as exc:
                self.close()
                raise ValueError("Odoo no ha respondido. Revisa el contenedor y su conexión a PostgreSQL.") from exc
            if not result.get("ok"):
                raise OdooOperationError(result.get("error", "Error al consultar Odoo."), result.get("diagnostic"))
            return result["result"]

    def inspect(self):
        info = self.call("inspect")
        self.databases, self.version = info["databases"], info["version"]
        self.database = info.get("database")
        if not self.url and self.database:
            self.url = self.call("base_url")
        return info

    def for_database(self, database):
        if database not in self.databases:
            raise ValueError("La base de datos no pertenece a las detectadas en el proyecto.")
        other = DockerOdooClient(self.project, database, self.python)
        other.version, other.databases = self.version, self.databases
        return other


def export_template(directory, template, source):
    """Write an importable Odoo XML record without overwriting module sources."""
    import uuid
    from datetime import datetime
    from lxml import etree
    from .demo import parse_xml

    root = parse_xml(source)
    for node in root.iter():
        if isinstance(node.tag, str):
            node.attrib.pop("data-editor-node", None)
    if root.tag in ("odoo", "data", "templates"):
        raise ValueError("Exporta la arquitectura de una sola plantilla, sin envoltorio odoo/data.")
    key = template.get("xml_id") or template.get("key") or f'local_report_{template["id"]}'
    document = etree.Element("odoo")
    record = etree.SubElement(document, "record", id=key, model="ir.ui.view")
    etree.SubElement(record, "field", name="name").text = template["name"]
    etree.SubElement(record, "field", name="type").text = "qweb"
    if template.get("key"):
        etree.SubElement(record, "field", name="key").text = template["key"]
    if template.get("inherit_xml_id"):
        etree.SubElement(record, "field", name="inherit_id", ref=template["inherit_xml_id"])
        etree.SubElement(record, "field", name="mode").text = template.get("view_mode", "extension")
    elif template.get("inherited"):
        raise ValueError("La vista padre no tiene identificador externo; no se puede generar una referencia exportable.")
    etree.SubElement(record, "field", name="arch", type="xml").append(root)
    output = Path(directory) / "report_editor_exports"
    filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)[:120] or "template"
    path = output / f'{filename}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.xml'
    content = etree.tostring(document, encoding="utf-8", xml_declaration=True, pretty_print=True)
    try:
        output.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)
    except OSError as exc:
        raise ValueError("No se pudo escribir el XML en report_editor_exports. Revisa los permisos del proyecto.") from exc
    return {"path": str(path), "filename": path.name, "xml": content.decode()}
