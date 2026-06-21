param(
    [string]$PilotJar = "",
    [string]$SysmlLibrary = "",
    [string]$Port = "",
    [string]$GradleExe = "",
    [string]$GradleUserHome = "",
    [string]$ServiceDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")
$LocalConfig = Join-Path $ScriptDir "pilot-real.local.ps1"

if (Test-Path -LiteralPath $LocalConfig) {
    . $LocalConfig
}

if (-not $PilotJar) {
    if ($env:SYVERN_PILOT_JAR) {
        $PilotJar = $env:SYVERN_PILOT_JAR
    } elseif (Get-Variable -Name JAR -Scope Local -ErrorAction SilentlyContinue) {
        $PilotJar = $JAR
    }
}

if (-not $SysmlLibrary) {
    if ($env:SYSML_LIBRARY_PATH) {
        $SysmlLibrary = $env:SYSML_LIBRARY_PATH
    } elseif (Get-Variable -Name LIB -Scope Local -ErrorAction SilentlyContinue) {
        $SysmlLibrary = $LIB
    }
}

if (-not $Port) {
    if ($env:PILOT_PORT) {
        $Port = $env:PILOT_PORT
    } elseif (Get-Variable -Name PILOT_PORT -Scope Local -ErrorAction SilentlyContinue) {
        $Port = $PILOT_PORT
    } else {
        $Port = "8888"
    }
}

if (-not $GradleExe) {
    if ($env:GRADLE_EXE) {
        $GradleExe = $env:GRADLE_EXE
    } elseif (Get-Variable -Name GRADLE_EXE -Scope Local -ErrorAction SilentlyContinue) {
        $GradleExe = $GRADLE_EXE
    } else {
        $GradleExe = "gradle"
    }
}

if (-not $GradleUserHome) {
    if ($env:GRADLE_USER_HOME) {
        $GradleUserHome = $env:GRADLE_USER_HOME
    } elseif (Get-Variable -Name GRADLE_USER_HOME -Scope Local -ErrorAction SilentlyContinue) {
        $GradleUserHome = $GRADLE_USER_HOME
    } else {
        $GradleUserHome = Join-Path $RootDir ".gradle-user-home"
    }
}

if (-not $ServiceDir) {
    $ServiceDir = Join-Path $RootDir "services\pilot-server"
}

if (-not $PilotJar -or -not (Test-Path -LiteralPath $PilotJar)) {
    throw "Pilot jar not found. Set `$JAR in scripts/pilot-real.local.ps1 or pass -PilotJar."
}

if (-not $SysmlLibrary -or -not (Test-Path -LiteralPath $SysmlLibrary)) {
    throw "SysML library path not found. Set `$LIB in scripts/pilot-real.local.ps1 or pass -SysmlLibrary."
}

if (-not (Test-Path -LiteralPath $ServiceDir)) {
    throw "Pilot service directory not found: $ServiceDir"
}

if ($GradleExe -ne "gradle" -and -not (Test-Path -LiteralPath $GradleExe)) {
    throw "Gradle executable not found: $GradleExe"
}

$PortListeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($PortListeners) {
    $OwnerIds = @($PortListeners | Select-Object -ExpandProperty OwningProcess -Unique)
    $Owners = @()
    foreach ($OwnerId in $OwnerIds) {
        $Process = Get-Process -Id $OwnerId -ErrorAction SilentlyContinue
        if ($Process) {
            $Owners += "$($Process.ProcessName)($OwnerId)"
        } else {
            $Owners += "pid $OwnerId"
        }
    }
    throw "Port $Port is already in use by $($Owners -join ', '). Stop the existing Pilot server or choose another -Port."
}

$env:PILOT_PORT = $Port
$env:PILOT_BACKEND = "real"
$env:SYSML_LIBRARY_PATH = $SysmlLibrary
$env:GRADLE_USER_HOME = $GradleUserHome

Write-Host "Starting SYVERN Pilot Server"
Write-Host "  Port: $env:PILOT_PORT"
Write-Host "  Jar:  $PilotJar"
Write-Host "  Lib:  $env:SYSML_LIBRARY_PATH"
Write-Host "  Gradle: $GradleExe"
Write-Host "  Gradle user home: $env:GRADLE_USER_HOME"

Push-Location $ServiceDir
try {
    & $GradleExe run -PwithPilot "-PpilotJar=$PilotJar"
} finally {
    Pop-Location
}
