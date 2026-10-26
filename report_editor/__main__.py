def main():
    import argparse
    from pathlib import Path
    import threading
    import webbrowser
    import uvicorn
    from .app import app
    from .project import ComposeProject, DockerOdooClient

    parser = argparse.ArgumentParser(description="Abre el editor de informes en un proyecto Odoo con Docker Compose.")
    parser.add_argument("directory", nargs="?", default=".", help="Directorio del proyecto (por defecto, el actual)")
    parser.add_argument("--service", help="Servicio Odoo del Compose, si no se puede detectar")
    parser.add_argument("--database", "-d", help="Base de datos Odoo, si hay varias")
    parser.add_argument("--compose-file", "-f", help="Fichero Compose alternativo")
    parser.add_argument("--python", default="python3", help="Ejecutable Python dentro del contenedor")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Probar el editor sin Docker ni Odoo")
    args = parser.parse_args()
    app.state.export_directory = Path(args.directory).resolve()
    if not args.demo:
        try:
            project = ComposeProject.discover(args.directory, args.service, args.compose_file)
            print(f"Proyecto: {project.directory}\nServicio Odoo: {project.service}\nDetectando bases de datos…", flush=True)
            client = DockerOdooClient(project, args.database, args.python)
            info = client.inspect()
            app.state.project_client = client
            print(f'Odoo {info["version"]} · Base de datos: {info["database"] or "seleccionar en el navegador"}', flush=True)
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
    address = f"http://127.0.0.1:{args.port}"
    print(f"Editor: {address}", flush=True)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(address)).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        if hasattr(app.state, "project_client"):
            app.state.project_client.close()


if __name__ == "__main__":
    main()
