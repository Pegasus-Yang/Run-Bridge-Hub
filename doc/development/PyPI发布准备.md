# Hub PyPI 发布准备

简体中文 · [English](PyPI发布准备.en.md)

当前准备版本为 **0.9.3**，Python 要求为 **3.14.x**。本手册用于把已审核源码构建为可上传 PyPI 的包；构建、检查、Git 推送与实际上传分别执行。用户尚未授权发布时，完成本地检查并保留产物。

## 包名与入口

| 项目 | 值 |
| --- | --- |
| PyPI 分发名 | `runbridge-hub` |
| Python 导入名 | `runbridge_hub` |
| CLI | `runbridge-hub` |
| 当前 wheel | `dist/runbridge_hub-0.9.3-py3-none-any.whl` |
| 当前源码包 | `dist/runbridge_hub-0.9.3.tar.gz` |
| 可选依赖 | `mcp`：MCP 服务端入口 |

普通 Python 环境可导入 `runbridge_hub`，CLI 由安装包入口生成。安装和帮助检查不会自动启动服务；Node 的浏览器及系统库仍按其手册单独准备。

## 1. 同步版本并核对源码

按[本地发布规范](版本发布与本地打包.md)同步 `pyproject.toml`、包内 `__version__`、`uv.lock`、中英文当前文档与安装命令。保留旧 tag、旧发行包、历史版本记录和验收基线。

`pyproject.toml` 使用 `README.en.md` 作为 `text/markdown` 长描述。中英文 README 的文件、图片及语言导航使用完整 GitHub URL，架构图使用静态 SVG；不依赖 GitHub 执行 Mermaid。短描述、Python 分类、许可证、作者、仓库和文档地址由项目元数据提供。

wheel 只选择当前 `src/runbridge_hub` 包，并包含必要运行资源及许可证。源码包另保留测试和当前用户文档；本地目录、设计与历史验收材料、参考目录顶层的原始核验 JSON/PNG 不属于发行内容。它们在仓库和本机按原有职责保留。

提交预期版本源码，确认工作树干净，记录提交号。以下构建、严格检查和发布命令均在**本仓库根目录**执行。

## 2. 同时构建两种发行包

```bash
uv build --out-dir dist --no-sources -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

不清空 `dist/` 中的旧版本；后续命令只指定上表的两个文件，不使用 `dist/*`。`--no-sources` 确认构建不依赖本机源码覆盖配置。

## 3. 严格检查 PyPI 元数据与长描述

```bash
uv tool run --from 'twine==7.0.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com twine check --strict dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

两份文件均应通过。Twine 是独立检查工具，不加入本包的运行依赖。还需检查包内版本、`Requires-Python`、MIT 声明、可选依赖、入口和 Hub 的 HTML/CSS/JS、图标及第三方许可证。严格检查不证明外部链接已公开或账号有上传权限。

## 4. 在独立目录安装实际 wheel

下面创建全新的检查目录与 `.venv`，验证真实安装包，不使用源码 editable 环境：

```bash
rb_release_check=$(mktemp -d)
uv venv --python 3.14 "$rb_release_check/.venv"
uv pip install --python "$rb_release_check/.venv/bin/python" "dist/runbridge_hub-0.9.3-py3-none-any.whl[mcp]" -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
"$rb_release_check/.venv/bin/python" -I -c 'import runbridge_hub; print(runbridge_hub.__version__); print(runbridge_hub.__file__)'
"$rb_release_check/.venv/bin/runbridge-hub" serve --help
```

应输出 0.9.3，导入路径位于新环境的 `site-packages`，帮助中有 `--settings`。随后在检查目录解析样例 YAML，核对相对路径和必需配置；只做发布准备时不运行 `serve` / `run`、登记或浏览器安装命令。基础安装与可选依赖应分别确认；安装 extra 不代表已验证真实浏览器执行。

## 5. 固定产物并检查公开链接

核对 wheel 和源码包中的源码与预期 Git 提交一致，在该提交创建附注标签 `v0.9.3`。记录两份文件的 SHA-256、构建提交、Twine 结果、安装来源和检查范围，保存在忽略的 `local/` 中。

实际上传前，先在获得授权后同步 GitHub 提交和标签。检查 README 的公开英文手册、许可证、图片与 SVG 返回正确内容；尚未推送的本地文件不能作为公开链接已经可用的证明。

## 6. 预演与实际上传

预演命令不上传文件，也不需要读取真实令牌：

```bash
uv publish --dry-run --trusted-publishing never --keyring-provider disabled --publish-url https://upload.pypi.org/legacy/ --check-url https://pypi.org/simple/ dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

正式上传只在取得用户授权、确认项目归属与文件摘要之后执行。操作者在发布进程环境配置 `UV_PUBLISH_TOKEN`，不把令牌写入命令参数、仓库或报告。PyPI 上传地址与阿里云下载镜像不是同一个入口。手动令牌发布使用：

```bash
uv publish --trusted-publishing never --keyring-provider disabled --publish-url https://upload.pypi.org/legacy/ --check-url https://pypi.org/simple/ dist/runbridge_hub-0.9.3-py3-none-any.whl dist/runbridge_hub-0.9.3.tar.gz
```

预演成功不等于账号校验或上线成功；PyPI 同版本文件不能覆盖。已发布后发现问题时提升版本，不移动旧 tag 或改名重用旧文件。本仓库暂不配置自动上传工作流。

## 7. 上传后的成功标准

核对 `https://pypi.org/pypi/runbridge-hub/0.9.3/json` 中的版本、英文长描述和两份文件。远端文件的 SHA-256 应与已核验的本地文件一致，再从官方返回的下载 URL 取回 wheel，重新在独立环境安装并检查导入路径、CLI、配置和 Hub 的 HTML/CSS/JS、图标及第三方许可证。镜像可能尚未同步，不能仅凭镜像搜索判断首次上传结果。

发布记录应区分：本地构建与检查、GitHub 同步、PyPI 上传、线上文件回读安装、真实服务/浏览器验收。它们是不同的验证层级。

参考：[uv 构建与发布](https://docs.astral.sh/uv/guides/package/)、[PyPI README 指南](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/)、[Twine](https://twine.readthedocs.io/en/stable/)。
