"""Fail closed if a wheel would silently omit the prebuilt workbench.

Data-file destinations are declared in pyproject.toml. Building never downloads
or installs JavaScript tools: run the declared TypeScript build first.
"""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class CheckedBuildPy(build_py):
    def run(self):
        web = Path("apps/web")
        required = [web / "dist/app/main.js", web / "index.html", Path("config/defaults.toml")]
        required.extend(web / "dist" / path.relative_to(web / "src").with_suffix(".js")
                        for path in (web / "src").rglob("*.ts")
                        if not path.name.endswith(".d.ts"))
        if any(not path.is_file() for path in required):
            raise RuntimeError("Missing workbench assets; build with npm run build before building the wheel.")
        super().run()


setup(cmdclass={"build_py": CheckedBuildPy})
