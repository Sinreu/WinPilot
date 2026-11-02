param(
    [Parameter(Mandatory=$false)]
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$Repository = 'WinPilot'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Нужен Git for Windows: https://git-scm.com/download/win'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'Нужен GitHub CLI: https://cli.github.com/'
}

gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Сначала выполните: gh auth login' }

if (-not (Test-Path '.git')) {
    git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'git init завершился с ошибкой' }
}

git add .
if ($LASTEXITCODE -ne 0) { throw 'git add завершился с ошибкой' }
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m 'Initial WinPilot safe Windows optimizer'
    if ($LASTEXITCODE -ne 0) { throw 'Нужна настройка git user.name / user.email или ошибка git commit' }
}

$remotes = @(git remote)
if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить список git remote' }
if ($remotes -contains 'origin') {
    throw 'Удалённый origin уже настроен. Выполните git push -u origin main вручную.'
}

# Private is the safe default: publishing public code is a user decision.
gh repo create $Repository --private --source . --remote origin --push
if ($LASTEXITCODE -ne 0) { throw 'Публикация не удалась — проверьте имя и доступ к GitHub.' }
Write-Host 'Проект опубликован в приватном GitHub-репозитории.' -ForegroundColor Green
