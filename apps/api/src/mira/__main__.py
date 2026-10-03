import uvicorn

from mira.config.loader import load_settings, project_root
from mira.entrypoints.http.app import create_app


def main() -> None:
    root = project_root()
    dotenv = root / ".env"
    settings = load_settings(root=root, env_file=dotenv if dotenv.is_file() else None)
    uvicorn.run(create_app(settings), host=settings.http.host, port=settings.http.port,
                workers=1, access_log=False, ws_max_size=32768, ws_max_queue=8)


if __name__ == "__main__":
    main()
