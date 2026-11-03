# Creates the self-signed certificate Apache uses for https://localhost. Browsers will warn about it.
# Git keeps the private key out of the repository. Run this once on each machine.
$root = Split-Path -Parent $PSScriptRoot
$folder = Join-Path $root 'deploy\apache\certs'
New-Item -ItemType Directory -Force $folder | Out-Null
$openssl = (Get-Command openssl -ErrorAction SilentlyContinue).Source
if (-not $openssl) { $openssl = 'C:\Program Files\Git\usr\bin\openssl.exe' }
& $openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj '/CN=localhost' `
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' `
    -keyout (Join-Path $folder 'earthscape.key') -out (Join-Path $folder 'earthscape.crt')
if ($LASTEXITCODE -ne 0) { throw 'OpenSSL could not create the certificate.' }
Write-Output "Certificate created in $folder"
