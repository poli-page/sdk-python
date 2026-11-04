# Releasing

## Versions

`poli-page` shares its major.minor with the Poli Page API: SDK `0.13.x` talks
to API `0.13`, passes the [API contract](https://github.com/poli-page/api-contract)
`v0.13.0`, and is released once the API runs that version. Patch numbers are
free: a fix to the SDK alone is a patch, whatever the API's patch. A change of
the API contract, a new SDK feature and a raise of the minimum Python version
are each a minor. The SDK may skip minors when it has nothing to ship for one.
Both `scripts/release.sh` and the Publish workflow refuse a version whose
major.minor differs from the contract version pinned in
`.github/workflows/ci.yml` (`scripts/check-contract-version.sh`).

## Steps

The release steps, from the version bump to the upload, are in
[CONTRIBUTING.md](CONTRIBUTING.md#releasing).
