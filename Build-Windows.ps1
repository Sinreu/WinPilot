$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Не найден Python Launcher (py). Установите Python 3.12 с python.org.'
}

py -3.12 -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Не удалось обновить pip' }
py -3.12 -m pip install 'pyinstaller>=6,<7'
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить PyInstaller' }
py -3.12 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Тесты не пройдены' }
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name WinPilot app.py
if ($LASTEXITCODE -ne 0) { throw 'Сборка завершилась с ошибкой' }
Write-Host "Готово: $PSScriptRoot\dist\WinPilot.exe" -ForegroundColor Green
