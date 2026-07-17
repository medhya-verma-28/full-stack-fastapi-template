# generate_from_examples.ps1

$ExamplesDirectory = "specmatic-test-requests"
$ProxyUrl = "http://localhost:9000"

# 1. Verification checks
if (-not (Test-Path $ExamplesDirectory)) {
    Write-Error "Target directory not found: $ExamplesDirectory"
    exit 1
}

# Fetch all JSON file pathways recursively from the target subdirectory
$ExampleFiles = Get-ChildItem -Path $ExamplesDirectory -Filter "*.json" -Recurse

if ($null -eq $ExampleFiles -or $ExampleFiles.Count -eq 0) {
    Write-Warning "No JSON file structures found inside $ExamplesDirectory"
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host " Found $($ExampleFiles.Count) pre-generated example files.                " -ForegroundColor Green
Write-Host " Streaming traces directly through proxy at: $ProxyUrl " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

# 2. Iterate and feed raw payloads dynamically through the proxy container 
$Counter = 1
foreach ($File in $ExampleFiles) {
    try {
        # Parse the JSON layout directly
        $JsonContent = Get-Content -Raw -Path $File.FullName | ConvertFrom-Json
        
        # Verify mandatory parent structure keys exist before extracting
        if ($null -eq $JsonContent.'http-request') {
            Write-Host "     ↳ Skip: File '$($File.Name)' is missing required 'http-request' block." -ForegroundColor Yellow
            $Counter++
            continue
        }

        # Extract target parameter metadata safely using parent context mappings
        $HttpRequest = $JsonContent.'http-request'
        $Method      = $HttpRequest.method
        $ApiPath     = $HttpRequest.path
        $Headers     = $HttpRequest.headers
        $Body        = $HttpRequest.body

        if ([string]::IsNullOrEmpty($Method) -or [string]::IsNullOrEmpty($ApiPath)) {
            Write-Host "     ↳ Skip: File '$($File.Name)' has blank request method or endpoint path." -ForegroundColor Yellow
            $Counter++
            continue
        }

        Write-Host "[$Counter/$($ExampleFiles.Count)] Processing: [$Method] $ApiPath ($($File.Name))" -ForegroundColor Cyan

        # Setup standard request variables directed at the proxy port
        $RequestArgs = @{
            Uri        = "$ProxyUrl$ApiPath"
            Method     = $Method
            Headers    = @{ "Accept" = "application/json" }
            TimeoutSec = 10
        }

        # Handle header mapping configurations if stored explicitly inside the files
        if ($null -ne $Headers) {
            foreach ($HeaderName in ($Headers.psobject.Properties.Name)) {

        $HeaderValue = $Headers.$HeaderName

        # Replace bearer token placeholder with the actual token
        if ($HeaderValue -is [string] -and $HeaderValue.Contains("{{OAUTH2_BEARER_TOKEN}}")) {
            $HeaderValue = $HeaderValue.Replace(
                "{{OAUTH2_BEARER_TOKEN}}",
                $env:OAUTH2_BEARER_TOKEN
            )
        }

        # Prevent overwrite duplication errors for built-in defaults
        if (-not $RequestArgs.Headers.ContainsKey($HeaderName)) {
            $RequestArgs.Headers.Add($HeaderName, $HeaderValue)
        }
        else {
            $RequestArgs.Headers[$HeaderName] = $HeaderValue
        }
    }
        }

        # Inject request payloads cleanly if present (POST, PUT, PATCH operations)
        # Query parameters
if ($null -ne $Query) {
    $pairs = @()

    foreach ($prop in $Query.PSObject.Properties) {
        $pairs += ("{0}={1}" -f `
            [System.Uri]::EscapeDataString($prop.Name),
            [System.Uri]::EscapeDataString([string]$prop.Value))
    }

    if ($pairs.Count -gt 0) {
        $RequestArgs.Uri += "?" + ($pairs -join "&")
    }
}

# Request body
if ($null -ne $Body) {

    $ContentType = $RequestArgs.Headers["Content-Type"]

    if ($ContentType -like "*application/x-www-form-urlencoded*") {

        # PowerShell automatically form-encodes hashtables
        if ($Body.form_data) {
            $RequestArgs.Body = $Body.form_data
        }
        else {
            $RequestArgs.Body = $Body
        }

    }
    else {

        $RequestArgs.Body = $Body | ConvertTo-Json -Depth 10

        if (-not $RequestArgs.Headers.ContainsKey("Content-Type")) {
            $RequestArgs.Headers["Content-Type"] = "application/json"
        }

    }
}
        $response = Invoke-RestMethod @RequestArgs

    }  catch {
    Write-Host "FAILED: $Method $ApiPath" -ForegroundColor Red

    if ($null -ne $response -and $null -ne $response.Content) {
        try {
            $body = $response.Content.ReadAsStringAsync().Result
            if (![string]::IsNullOrWhiteSpace($body)) {
                Write-Host $body -ForegroundColor Yellow
            }
        }
        catch {
            Write-Host $_.Exception.Message -ForegroundColor Yellow
        }
    }

    if ($_.Exception.Message) {
        Write-Host $_.Exception.Message -ForegroundColor Red
    }

    
} $Counter++
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Extraction Pipeline Finished!                            " -ForegroundColor Green
Write-Host " Press Ctrl+C in your Proxy Docker Terminal to write spec." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
