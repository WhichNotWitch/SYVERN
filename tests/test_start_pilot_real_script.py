import socket
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "start-pilot-real.ps1"
SERVICE_DIR = ROOT / "services" / "pilot-server"


def test_start_pilot_real_fails_before_gradle_when_port_is_occupied(tmp_path):
    pilot_jar = tmp_path / "pilot.jar"
    pilot_jar.write_text("placeholder", encoding="utf-8")
    sysml_library = tmp_path / "sysml.library"
    sysml_library.mkdir()
    gradle_marker = tmp_path / "gradle-called.txt"
    fake_gradle = tmp_path / "gradle.cmd"
    fake_gradle.write_text(f"@echo off\r\necho called > \"{gradle_marker}\"\r\n", encoding="utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                "-PilotJar",
                str(pilot_jar),
                "-SysmlLibrary",
                str(sysml_library),
                "-Port",
                str(port),
                "-GradleExe",
                str(fake_gradle),
                "-GradleUserHome",
                str(tmp_path / "gradle-home"),
                "-ServiceDir",
                str(SERVICE_DIR),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert f"Port {port} is already in use" in output
    assert not gradle_marker.exists()
