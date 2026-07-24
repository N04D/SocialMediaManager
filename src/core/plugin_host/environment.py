"""Plugin host environment preparation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from .errors import PluginHostEnvironmentError
from .models import PluginHostEnvironmentSpec


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PluginHostEnvironmentManager:
    def __init__(self, install_root: str | Path, environment_root: str | Path) -> None:
        self.install_root = Path(install_root)
        self.environment_root = Path(environment_root)

    def prepare(self, plugin_id: str, plugin_version: str) -> PluginHostEnvironmentSpec:
        self._verify_installed_files(plugin_id, plugin_version)
        if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
            raise PluginHostEnvironmentError("plugin_host.env.invalid_plugin", "Plugin id is not path-safe.")
        version_root = self.install_root / plugin_id / "installs" / plugin_version
        if not version_root.exists():
            raise PluginHostEnvironmentError("plugin_host.env.install_missing", "Installed plugin version is missing.")
        env_root = self.environment_root / plugin_id / plugin_version
        if env_root.exists():
            shutil.rmtree(env_root)
        builder = venv.EnvBuilder(with_pip=False, system_site_packages=False, clear=True)
        builder.create(env_root)
        python = env_root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        site_packages = self._site_packages(env_root)
        marker = site_packages / "_smm_no_pip_runtime.py"
        marker.write_text('"""Host-owned marker: pip/ensurepip runtime use is blocked by policy."""\n')
        self._copy_host_runtime(site_packages)
        (env_root / "host-environment.json").write_text(
            json.dumps(
                {
                    "plugin_id": plugin_id,
                    "plugin_version": plugin_version,
                    "system_site_packages": False,
                    "user_site": False,
                    "pip": "blocked",
                    "ensurepip": "blocked",
                    "source_tree_on_sys_path": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        checksum = _sha256_text(f"{plugin_id}:{plugin_version}:{version_root}:{python}")
        return PluginHostEnvironmentSpec(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            artifact_sha256=self._artifact_hash(plugin_id, plugin_version),
            manifest_checksum=self._manifest_checksum(version_root),
            entrypoint=self._entrypoint(version_root, plugin_id),
            environment_checksum=checksum,
            python_executable=str(python),
            status="prepared",
        )

    def verify(self, plugin_id: str, plugin_version: str) -> PluginHostEnvironmentSpec:
        env_root = self.environment_root / plugin_id / plugin_version
        python = env_root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if not (env_root / "host-environment.json").exists():
            return self.prepare(plugin_id, plugin_version)
        if not python.exists():
            raise PluginHostEnvironmentError("plugin_host.env.missing_python", "Plugin host Python is missing.")
        return PluginHostEnvironmentSpec(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            artifact_sha256=self._artifact_hash(plugin_id, plugin_version),
            manifest_checksum=self._manifest_checksum(self.install_root / plugin_id / "installs" / plugin_version),
            entrypoint=self._entrypoint(self.install_root / plugin_id / "installs" / plugin_version, plugin_id),
            environment_checksum=_sha256_text(
                f"{plugin_id}:{plugin_version}:{self.install_root / plugin_id / 'installs' / plugin_version}:{python}"
            ),
            python_executable=str(python),
            status="verified",
        )

    def start_command(self, spec: PluginHostEnvironmentSpec) -> list[str]:
        return [spec.python_executable, "-I", "-m", "plugin_host_runtime"]

    def _site_packages(self, env_root: Path) -> Path:
        candidates = list(env_root.glob("lib/python*/site-packages")) + list(env_root.glob("Lib/site-packages"))
        if not candidates:
            raise PluginHostEnvironmentError(
                "plugin_host.env.site_packages_missing", "Virtualenv site-packages missing."
            )
        return candidates[0]

    def _copy_host_runtime(self, site_packages: Path) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
        for source, target in [
            (repo_root / "src" / "plugin_host_runtime", site_packages / "plugin_host_runtime"),
            (repo_root / "src" / "plugin_sdk", site_packages / "src" / "plugin_sdk"),
            (repo_root / "src" / "core", site_packages / "src" / "core"),
            (repo_root / "plugin_sdk", site_packages / "plugin_sdk"),
        ]:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, ignore=ignore)
        for package_init in [site_packages / "src" / "__init__.py", site_packages / "src" / "core" / "__init__.py"]:
            package_init.parent.mkdir(parents=True, exist_ok=True)
            if not package_init.exists():
                package_init.write_text('"""Host-owned runtime package."""\n')

    def _artifact_hash(self, plugin_id: str, plugin_version: str) -> str:
        ledger = self._list_installed()
        for row in ledger:
            if row.get("plugin_id") == plugin_id and row.get("plugin_version") == plugin_version:
                return str(row.get("artifact_sha256") or "")
        return ""

    def _list_installed(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for ledger in self.install_root.glob("*/install-ledger.json"):
            rows.extend(json.loads(ledger.read_text()))
        return rows

    def _verify_installed_files(self, plugin_id: str, plugin_version: str) -> None:
        target = self.install_root / plugin_id / "installs" / plugin_version
        if not target.exists():
            raise PluginHostEnvironmentError("plugin_host.env.install_missing", "Installed plugin version is missing.")
        checksum = self._installed_manifest_checksum(target)
        for row in self._list_installed():
            if row.get("plugin_id") == plugin_id and row.get("plugin_version") == plugin_version:
                if row.get("installed_file_manifest_checksum") != checksum:
                    raise PluginHostEnvironmentError("plugin_host.env.file_drift", "Installed plugin files drifted.")
                return
        raise PluginHostEnvironmentError("plugin_host.env.ledger_missing", "Installed plugin ledger is missing.")

    def _manifest_checksum(self, version_root: Path) -> str:
        manifests = sorted(version_root.rglob("*.manifest.json"))
        if not manifests:
            return ""
        return hashlib.sha256(manifests[0].read_bytes()).hexdigest()

    def _entrypoint(self, version_root: Path, plugin_id: str) -> str:
        entrypoints = sorted(version_root.rglob("entry_points.txt"))
        for path in entrypoints:
            text = path.read_text()
            for line in text.splitlines():
                if line.startswith(plugin_id):
                    return line.split("=", maxsplit=1)[1].strip()
        return ""

    def _installed_manifest_checksum(self, root: Path) -> str:
        rows = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if path.name == "INSTALLER":
                continue
            rows.append(
                f"{path.relative_to(root)}:{hashlib.sha256(path.read_bytes()).hexdigest()}:{path.stat().st_size}"
            )
        return hashlib.sha256("\n".join(rows).encode()).hexdigest()

    def probe_no_user_site(self, spec: PluginHostEnvironmentSpec) -> bool:
        result = subprocess.run(
            [spec.python_executable, "-I", "-c", "import site; print(site.ENABLE_USER_SITE)"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() in {"False", "None"}


__all__ = ["PluginHostEnvironmentManager"]
