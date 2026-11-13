# Remote Webcam Client PowerShell Launcher
Set-Location -Path $PSScriptRoot

if (Test-Path "$PSScriptRoot\.venv\Scripts\Activate.ps1") {
    & "$PSScriptRoot\.venv\Scripts\Activate.ps1"
} elseif (Test-Path "$PSScriptRoot\venv\Scripts\Activate.ps1") {
    & "$PSScriptRoot\venv\Scripts\Activate.ps1"
}

python "$PSScriptRoot\client.py" @args
