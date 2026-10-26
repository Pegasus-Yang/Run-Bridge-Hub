# Hub GitHub Actions 与 Release

简体中文 · [English](GitHubActions与Release.en.md)

工作流负责验证和 GitHub Release 发布。GitHub Release 与 PyPI 是独立的分发入口；本配置不上传 PyPI，也不读取 PyPI 发布令牌。

## 触发方式

| 操作 | 工作流 | 结果 |
| --- | --- | --- |
| 普通分支提交、Pull Request | `CI` | 验证、构建、安装检查，保存 Actions Artifact |
| 推送 `v*` 标签 | `Release` | 检出标签源码，检查成功后发布 Release |
| 在默认分支手动填写已有标签 | `Release` | 按原标签源码补发 Release，无需移动标签 |

定义见 [ci.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/ci.yml)、[validate.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/validate.yml)、[release.yml](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/.github/workflows/release.yml)。可复用的 `validate.yml` 统一普通提交与发布检查；发布任务使用同一次验证产生的附件。

## 验证范围与产物

运行环境为 Ubuntu 24.04、Python 3.14、uv 0.13.5。使用仓库根目录 `.venv`、`uv.lock`、全部 extras 和项目约定的阿里云安装源。

1. 核对 `pyproject.toml`、包内 `__version__`、锁文件版本；发布标签必须等于 `v` 加包版本，检出的提交必须等于标签提交。
2. 执行 `pytest tests -q -m 'not browser'`。真实浏览器测试需要专用环境与显式启用，不计入本工作流的验收。
3. 执行 `uv build --out-dir dist --no-sources`，先构建源码包，再从源码包构建 wheel；Twine 严格检查元数据和英文长描述。
4. 逐文件核对发行内容与检出源码，在源码目录之外新建 `.venv`，验证基础及 extras 安装、site-packages 来源、CLI 帮助、样例 YAML 相对路径。Hub 另核对网页资源与第三方图标许可证。安装检查不启动业务服务或浏览器。
5. 生成 `SHA256SUMS`、`release-manifest.json` 和发布说明。manifest 记录实际构建源码提交与工作流提交，二者在补发旧标签时可以不同。

Actions Artifact 名为 `distribution-运行ID-重试次数`，保留 14 天，包含已验证的两个发行包、摘要、manifest 和发布说明。GitHub Release 附件为 `.whl`、`.tar.gz`、`SHA256SUMS`、`release-manifest.json`；发布说明放在 Release 正文。

发布先创建草稿并上传附件，随后从 GitHub 下载回读摘要，全部匹配后才公开。已有 Release 或草稿时停止，不覆盖附件或移动标签。重新运行失败任务前先核对日志和已有草稿；维护者处理未完成草稿后再执行。

## 自动发布新版本

先按[本地打包规范](版本发布与本地打包.md)完成版本同步、检查、提交与本地打包，再推送该提交及附注标签。新标签提交本身应包含工作流定义。普通分支提交不会发布 Release。

下载入口：[GitHub Releases](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases)。CI 构建和本地构建分别记录文件摘要，不以文件名相同作为二者内容相同的证明；不要覆盖本地已保留的旧发行包。

## 手动补发已有标签

`v0.9.3` 创建时还没有工作流，因此从 **main** 运行新版 `Release`，在输入框填写 **v0.9.3**；不要把运行工作流的分支下拉框切到旧标签。工作流会单独检出 `refs/tags/v0.9.3` 构建。

GitHub 页面：Actions → Release → Run workflow → Branch `main` → tag `v0.9.3` → Run workflow。也可在已完成 GitHub CLI 登录的机器执行：

```bash
gh workflow run release.yml --repo Pegasus-Yang/Run-Bridge-Hub --ref main -f tag=v0.9.3
```

在 Actions 中确认验证和发布两个任务均成功，再打开 [Release](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases/tag/v0.9.3) 检查附件。下载四份附件到同一独立目录后执行：

```bash
sha256sum --check SHA256SUMS
```

macOS 可用 `shasum -a 256 -c SHA256SUMS`。按安装手册在全新 `.venv` 安装实际下载的 wheel，确认版本和导入来源；仅有工作流排队或 Release 标题并不代表附件验收完成。

## 权限与排障

- 普通验证只有 `contents: read`，发布任务单独使用内置 `GITHUB_TOKEN` 的 `contents: write`；无需给 PR 提供发布秘密。外部 Actions 固定提交 SHA。
- 看不到 Run workflow：确认配置已在默认分支，操作者具有写权限，并选择 `Release`。
- 版本不一致：修正新版本提交或选择对应标签，不移动已发布标签来绕过检查。
- 依赖安装失败：检查 Actions 日志和安装源连通性，区分安装失败与测试失败。
- 出现已有 Release：核对现有附件和摘要，不自动覆盖或重复发布。
- PyPI 发布继续按 [PyPI 发布准备](PyPI发布准备.md)单独授权和核验；本工作流没有上传步骤。
