$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, then retry.' }
& ./.venv/Scripts/python.exe app.py
