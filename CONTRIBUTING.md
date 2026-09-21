# Contributing to THE ARK

## Attribution Requirement

**All forks, derivative works, and redistributions must retain full attribution.**

When forking this repository you **must** keep:

1. The `LICENSE` file (MIT) intact and unmodified
2. The `NOTICE` file intact and unmodified
3. The original copyright line: `Copyright (c) 2025 UncleT-cyber`
4. A visible acknowledgment in your README:

   ```
   Based on / Derived from THE ARK (ArkGeo) by UncleT-cyber
   https://github.com/UncleT-cyber/Ark-Geo
   ```

Stripping or altering these attributions is a license violation and will be reported.

**Note:** The CAI (Cybersecurity AI) Robotics Framework included in this project retains its
own dual licensing terms (MIT + Research-Use). CAI components under the Research-Use License
are not covered by this project's MIT license. See `arkgeo-backend/cai/LICENSE` for details.

## Code Contributions

If you want to contribute back to this project:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make your changes
4. Run the test suite (`cd arkgeo-backend && python -m pytest tests/ -q`)
5. Submit a pull request with a clear description of what changed and why

## Reporting Issues

Open an issue on GitHub. Include:
- Steps to reproduce
- Expected vs actual behavior
- Python version, OS, and relevant dependency versions

## Code Style

- Python: follow existing patterns in the codebase
- TypeScript/React: match existing component conventions
