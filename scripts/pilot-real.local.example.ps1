# Copy this file to scripts/pilot-real.local.ps1 and replace the paths.
# The local file is ignored by git.

$JAR = "C:\path\to\jupyter-sysml-kernel-0.59.0-all.jar"
$LIB = "C:\Users\16508\Documents\Projects\SYVERN\data\sft\raw_sources\sysml-v2-release\sysml.library"
$env:SYSML_LIBRARY_PATH = $LIB

# SYVERN expects the Pilot HTTP service here by default.
$PILOT_PORT = "8888"

# Optional: set this when Gradle is installed inside a Conda env or another
# directory that is not on PATH.
$GRADLE_EXE = "C:\path\to\gradle.bat"

# Optional: set this to avoid a broken global ~/.gradle/native cache.
# If omitted, scripts/start-pilot-real.ps1 uses .gradle-user-home in the repo.
$GRADLE_USER_HOME = "C:\path\to\isolated-gradle-user-home"
