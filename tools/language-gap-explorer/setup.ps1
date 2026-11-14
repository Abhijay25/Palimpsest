$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
& ./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, then retry.' }
& ./.venv/Scripts/python.exe prepare.py
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed. Rerun to resume.' }
& ./.venv/Scripts/python.exe local_translation.py --install
if ($LASTEXITCODE -ne 0) { throw 'Local translation model setup failed. Rerun to resume.' }
& ./.venv/Scripts/python.exe watchlist.py --seed-demo
if ($LASTEXITCODE -ne 0) { throw 'Watchlist initialization failed. Rerun to resume.' }
