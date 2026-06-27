# Use this script to load local env vars and start the bot.
# Copy .env.example to .env and fill in your BOT_TOKEN, API_ID, and API_HASH.

$envFile = Join-Path $PSScriptRoot ".env"
if (-Not (Test-Path $envFile)) {
    Write-Host "Missing .env file. Copy .env.example to .env and fill in your values." -ForegroundColor Yellow
    exit 1
}

Get-Content $envFile | ForEach-Object {
    if ($_ -and -not $_.StartsWith("#")) {
        $parts = $_ -split "=", 2
        if ($parts.Length -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            if ($name -and $value) {
                Set-Item -Path "Env:$name" -Value $value
            }
        }
    }
}

python "$PSScriptRoot\app.py"
