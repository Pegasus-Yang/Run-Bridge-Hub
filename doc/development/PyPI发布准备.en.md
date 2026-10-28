# Hub PyPI release preparation

[简体中文](PyPI发布准备.md) · English

Current release: **0.9.3**, available on [PyPI](https://pypi.org/project/runbridge-hub/0.9.3/), requiring Python **3.14.x**. The wheel and source distribution match the GitHub Release digests. This guide covers builds, checks, Git pushes, authorized uploads, and remote verification. Keep future release artifacts local until publication is authorized.

For the complete sequence, artifact reuse, English metadata, and troubleshooting, see the [publishing workflow](发布流程与注意事项.en.md).

## Distribution and entry points

| Item | Value |
| --- | --- |
| PyPI distribution | `runbridge-hub` |
| Python import | `runbridge_hub` |
| CLI | `runbridge-hub` |
| Wheel | `dist/runbridge_hub-0.9.3-py3-none-any.whl` |
| Source archive | `dist/runbridge_hub-0.9.3.tar.gz` |
| Optional dependencies | `mcp`: MCP server entry |

An ordinary Python environment imports `runbridge_hub`; installation creates the CLI. Installation/help checks do not start services. Node browser binaries/system libraries are prepared separately.

## 1. Match versions and source

Follow the [local release rules (Chinese)](版本发布与本地打包.md) to synchronize metadata, package `__version__`, lockfile, current bilingual docs, and installation commands. Preserve historical versions, records, artifacts, and tag targets.

Metadata uses `README.en.md` as the `text/markdown` long description. Both READMEs use complete GitHub URLs for files, images, and language navigation, with static SVG diagrams rather than GitHub-only Mermaid rendering. Metadata supplies the English summary, Python classifiers, MIT license, author, source, and documentation URLs.

The wheel explicitly selects `src/runbridge_hub`, required runtime assets, and licenses. The source archive additionally retains tests and current user manuals. Local folders, design/history/acceptance material, and top-level reference JSON/PNG evidence are outside the distribution; their repository/local ownership is unchanged.

Commit the intended version, confirm a clean working tree, and record the commit. Run the following build/check/upload commands from the **repository root**.

## 2. Build wheel and source archive

```bash
uv build --out-dir dist --no-sources -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

Retain older `dist/` artifacts. Use the two exact filenames above, not `dist/*`. `--no-sources` checks independence from local source overrides.

## 3. Check metadata and rendered description

```bash
uv tool run --from 'twine==7.0.0' --with 'readme-renderer[md]==46.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com twine check --strict dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

Both must pass. Twine is an isolated checking tool, not a runtime dependency. Also check versions, Requires-Python, MIT declarations, optional dependencies, entry points, and Hub HTML/CSS/JS, icons, and third-party license. Strict validation does not prove public link availability or upload permission.

## 4. Install the actual wheel independently

Create a fresh check directory and `.venv`, rather than testing an editable source installation:

```bash
rb_release_check=$(mktemp -d)
uv venv --python 3.14 "$rb_release_check/.venv"
uv pip install --python "$rb_release_check/.venv/bin/python" "dist/runbridge_hub-0.9.3-py3-none-any.whl[mcp]" -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
"$rb_release_check/.venv/bin/python" -I -c 'import runbridge_hub; print(runbridge_hub.__version__); print(runbridge_hub.__file__)'
"$rb_release_check/.venv/bin/runbridge-hub" serve --help
```

Expect 0.9.3, imports from the new `site-packages`, and `--settings` in help. Parse sample YAML in that check directory and verify relative paths/required fields. Preparation-only checks do not execute service startup, enrollment, or browser installation. Verify base and optional installs separately; installing an extra is not live browser acceptance.

## 5. Freeze artifacts and check public links

Match packaged sources against the intended commit and create annotated tag `v0.9.3` on it. Record SHA-256, commit, Twine results, installation origin, and scope in ignored `local/`.

Before upload, synchronize GitHub commits/tags with authorization. Verify publicly served English manuals, license, images, and SVGs. A local unpushed file does not prove an uploaded description's link is reachable.

## 6. Dry run and authorized upload

This dry run uploads nothing and needs no real token:

```bash
env -u UV_PUBLISH_TOKEN -u UV_PUBLISH_USERNAME -u UV_PUBLISH_PASSWORD \
  -u UV_PUBLISH_URL -u UV_PUBLISH_CHECK_URL -u UV_PUBLISH_INDEX \
  uv publish --no-config --dry-run --trusted-publishing never --keyring-provider disabled --publish-url https://upload.pypi.org/legacy/ --check-url https://pypi.org/simple/ dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

The commands below remove publishing settings inherited from other registries only in the child process; they do not change the parent shell. uv reads `UV_PUBLISH_TOKEN`, not `PYPI_TOKEN`. If the existing token is named `PYPI_TOKEN`, prefix the upload command with `UV_PUBLISH_TOKEN="${PYPI_TOKEN:?Configure PYPI_TOKEN in the environment}"` to map it for that process only. Do not print the value or enable shell tracing.

Upload only after user authorization, project ownership confirmation, and digest review. Configure `UV_PUBLISH_TOKEN` in the publishing process environment, never as a literal argument or in source/reports. The PyPI upload endpoint differs from the Aliyun download mirror. Manual token publication uses:

```bash
env -u UV_PUBLISH_USERNAME -u UV_PUBLISH_PASSWORD \
  -u UV_PUBLISH_URL -u UV_PUBLISH_CHECK_URL -u UV_PUBLISH_INDEX \
  uv publish --no-config --trusted-publishing never --keyring-provider disabled --publish-url https://upload.pypi.org/legacy/ --check-url https://pypi.org/simple/ dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

Dry-run success is not account validation or publication. PyPI files cannot be overwritten; fix an uploaded release with a new version and tag. The [GitHub Actions workflows](GitHubActions与Release.en.md) validate and publish GitHub Releases without uploading to PyPI.

## 7. Verify after upload

Check `https://pypi.org/pypi/runbridge-hub/0.9.3/json` for the version, English description, and both artifacts. Remote SHA-256 must match the checked local files. Download the official returned wheel, install it in another fresh environment, and verify import origin, CLI, settings, and Hub HTML/CSS/JS, icons, and third-party license. Mirrors may lag, so a mirror search alone does not establish first-publication status.

Record local package validation, GitHub synchronization, PyPI upload, remote artifact download/install, and actual service/browser acceptance separately.

References: [uv build/publish](https://docs.astral.sh/uv/guides/package/), [PyPI README guidance](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/), [Twine](https://twine.readthedocs.io/en/stable/).
