# Contributing

[简体中文](CONTRIBUTING.md) · English

Contributions to RunBridge Hub code, documentation, and examples are welcome. Maintained by [Pegasus-Yang](https://github.com/Pegasus-Yang).

## Report an issue or propose a change

Use this repository's [Issues](https://github.com/Pegasus-Yang/Run-Bridge-Hub/issues). Include both component versions, OS, Python version, browser mode, minimal steps, expected and actual results, and redacted errors. A request ID helps diagnose an execution problem.

Keep enrollment and claim credentials, Node identities, access tokens, browser profiles, and dashboard links containing tokens private. Report local browser startup, connection, or capture problems in the [Node repository](https://github.com/Pegasus-Yang/Run-Bridge-Node/issues).

## Prepare a contribution

1. Fork the repository and create a branch. Discuss major behavior or protocol changes in an Issue, including scope and compatibility.
2. Use `uv` and the repository's root `.venv`. From the cloned repository, prepare the development environment:

```bash
uv sync --extra mcp -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/python -m pytest tests -q
```

3. Keep changes related to the goal. Add a pytest regression that reproduces a bug when fixing one, and update current user documentation for behavior changes. Maintain both language versions and their links.
4. Explain the problem, resulting behavior, validation results, and any unperformed checks in the Pull Request.

Check the [Node implementation](https://github.com/Pegasus-Yang/Run-Bridge-Node) for changes to methods, objects, protocols, or lifecycle, and link any corresponding change. Use isolated settings, identities, and databases for live integration.

Repository rules are in [AGENTS.md (Chinese)](AGENTS.md). The [development manual (Chinese)](doc/development/本地开发与联调.md) covers builds and isolated integration. User-facing runtime guides are indexed in [English documentation](doc/README.en.md).

## License

Contributions are provided under the [MIT License](LICENSE). Identify the source of third-party code or assets and retain their license and copyright notices.
