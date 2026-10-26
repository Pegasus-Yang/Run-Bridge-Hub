# Hub GitHub Actions and Releases

[简体中文](GitHubActions与Release.md) · English

These workflows validate packages and publish GitHub Releases. PyPI is a separate destination: this configuration does not upload to PyPI or read a PyPI publishing token.

## Triggers

| Event | Workflow | Result |
| --- | --- | --- |
| Branch push or pull request | `CI` | Tests, builds, installed-wheel checks, and an Actions artifact |
| Push of a `v*` tag | `Release` | Check out the tag and publish after validation |
| Manual run on the default branch with an existing tag | `Release` | Backfill a release from the original tag without moving it |

Definitions: [ci.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/ci.yml), [validate.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/validate.yml), and [release.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/release.yml). The reusable validation workflow supplies the same checks for ordinary commits and releases. Publishing consumes the exact artifact from that validation run.

## Checks and artifacts

The runner uses Ubuntu 24.04, Python 3.14, and uv 0.13.5, with the root `.venv`, lockfile, all extras, and the project's Aliyun installation arguments. Before strict `--locked` synchronization, the workflow restores the default registry recorded in `uv.lock` (the current tags use Tsinghua). This accounts for the author's local `UV_DEFAULT_INDEX` override without rewriting historical lockfiles or changing dependency versions.

1. Match project metadata, package `__version__`, and the lockfile. A release tag must be `v` plus the package version, and its commit must match the checked-out source.
2. Run `pytest tests -q -m 'not browser'`. Real browser tests require a dedicated environment and explicit opt-in; this workflow does not claim that acceptance.
3. Run `uv build --out-dir dist --no-sources`, building the wheel from the source distribution, followed by strict Twine metadata and English-description checks.
4. Compare archive contents with the checked-out files. In a new `.venv` outside the source directory, check base and extra installs, site-packages origin, CLI help, and sample YAML paths. Hub also checks dashboard assets and the third-party icon license. Installation checks do not start application services or browsers.
5. Generate `SHA256SUMS`, `release-manifest.json`, and release notes. The manifest identifies both the source commit and workflow commit, which may differ when backfilling an old tag.

The Actions artifact is named `distribution-RUN_ID-RUN_ATTEMPT`, retained for 14 days, and contains both distributions, checksums, manifest, and notes. Published Release assets are the wheel, source archive, `SHA256SUMS`, and `release-manifest.json`; notes appear in the release body.

Publishing first uploads a draft, downloads its assets again, verifies checksums, and only then makes it public. An existing release or draft stops publication; assets and tags are not overwritten. Inspect logs and any incomplete draft before retrying; a maintainer handles that draft first.

## Publish a new version

Follow the [local packaging guide (Chinese)](版本发布与本地打包.md) to synchronize versions, validate, commit, and build locally. Push the release commit and its annotated tag. A new tag's commit must include the workflow files. Branch pushes do not publish releases.

Download from [GitHub Releases](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases). Record CI and local build digests separately; matching filenames do not prove identical contents. Preserve existing local distributions.

## Backfill an existing tag

Tag `v0.9.3` predates these workflows. Run the new `Release` workflow from **main**, with **v0.9.3** as its input. Keep the workflow branch dropdown on `main`; the workflow separately checks out `refs/tags/v0.9.3` for the build.

In GitHub: Actions → Release → Run workflow → Branch `main` → tag `v0.9.3` → Run workflow. With an authenticated GitHub CLI:

```bash
gh workflow run release.yml --repo Pegasus-Yang/Run-Bridge-Hub --ref main -f tag=v0.9.3
```

Confirm both validation and publication jobs succeed, then inspect the [release](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases/tag/v0.9.3) and its assets. Download all four assets into one separate directory and run:

```bash
sha256sum --check SHA256SUMS
```

On macOS use `shasum -a 256 -c SHA256SUMS`. Install the downloaded wheel into a fresh `.venv` and verify its version and import origin. A queued run or release title alone does not establish successful artifact delivery.

## Permissions and troubleshooting

- Validation uses `contents: read`; the publisher alone uses the built-in `GITHUB_TOKEN` with `contents: write`. PRs receive no publishing secret. External Actions are pinned to commit SHAs.
- No Run workflow button: confirm the workflow exists on the default branch, you have write permission, and `Release` is selected.
- Version mismatch: correct a new release commit or select its matching tag; do not move an existing published tag.
- Dependency installation fails: inspect the log and package-index connectivity before interpreting this as a test failure.
- Release already exists: inspect assets and checksums; automatic replacement is intentionally disabled.
- PyPI publication remains a separate authorized operation under [PyPI preparation](PyPI发布准备.en.md); there is no upload step here.
