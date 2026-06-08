# GitHub Actions — отключены

Workflows переименованы в `*.yml.disabled` (GitHub Actions читает только
`*.yml`/`*.yaml`). Чтобы снова включить — переименовать обратно в `*.yml`.

Альтернатива: гонять локально через `pytest -q` / `npm test` / `npm run build`
перед коммитом (см. CLAUDE.md → «Проверка перед коммитом»).
