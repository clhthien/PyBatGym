$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $expected = 'sha256:f35b3ef759ed11fb3bc0e4bd0e780ef1fdeda77ea750fb39552ed3eb8b170576'
    $actual = docker image inspect ghcr.io/clhthien/pybatgym:latest --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0 -or $actual -ne $expected) { throw 'Base image differs from the verified release environment.' }
    docker tag $expected pybatgym-release-base:f35b3ef759ed
    if ($LASTEXITCODE -ne 0) { throw 'Could not tag verified local base.' }
    docker build --pull=false -f Dockerfile.release -t ghcr.io/clhthien/pybatgym:local-20261120 .
    if ($LASTEXITCODE -ne 0) { throw 'Release build failed.' }
} finally { Pop-Location }
