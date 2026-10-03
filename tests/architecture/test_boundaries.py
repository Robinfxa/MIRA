"""Architecture rules are executable, not just diagrams in a README."""
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"apps/api/src/mira"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node,ast.Import): yield from (alias.name for alias in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module: yield node.module


def test_domain_has_no_framework_config_or_adapter_dependencies():
    allowed={"dataclasses","enum","typing","mira.domain"}
    for path in (SOURCE/"domain").glob("*.py"):
        for name in imports(path):
            assert any(name==root or name.startswith(root+".") for root in allowed),(path,name)


def test_application_never_imports_adapters_bootstrap_or_transport():
    forbidden=("mira.adapters","mira.bootstrap","mira.config","mira.entrypoints","fastapi","uvicorn")
    for path in (SOURCE/"application").rglob("*.py"):
        assert not any(name.startswith(forbidden) for name in imports(path)),path


def test_environment_reads_only_in_configuration_loader():
    for path in SOURCE.rglob("*.py"):
        if path.name=="loader.py" and path.parent.name=="config": continue
        source=path.read_text()
        for marker in ["os.environ","os.getenv","dotenv_values(","load_dotenv("]:
            assert marker not in source,(path,marker)


def test_provider_construction_only_in_composition_root():
    for path in (SOURCE/"application").rglob("*.py"):
        assert "MockGenerationBackend(" not in path.read_text()
        assert "FixtureReviewBackend(" not in path.read_text()


def test_generated_contracts_do_not_drift():
    subprocess.run([sys.executable,str(ROOT/"tools/export_contracts.py"),"--check"],check=True,cwd=ROOT)


def test_reference_test_catalogue_not_marked_passed():
    path=ROOT/"docs/reference/architecture-v0.6/docs/architecture/appendices/acceptance-catalog.json"
    assert path.exists()
    assert '"passed"' not in path.read_text().lower()


def test_module_import_does_not_read_environment_or_connect_network():
    code = """
import os,socket
class Forbidden(dict):
 def get(self,*a,**k): raise AssertionError('import-time environment read')
# Import framework first: this assertion targets our module, not third-party setup.
import fastapi,uvicorn
from mira.config import loader
loader.load_settings=lambda **kw: (_ for _ in ()).throw(AssertionError('load at import'))
socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network'))
import mira.entrypoints.http.app
import mira.bootstrap.container
"""
    subprocess.run([sys.executable,"-c",code],check=True,cwd=ROOT,
                   env={**__import__('os').environ,"PYTHONPATH":str(ROOT/"apps/api/src")})
