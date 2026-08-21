# Project Control

«Борис по парам» сохраняет существующий автономный формат `planner-solving-offline` и транзакционный `install_or_update.sh`. Для единого контроллера поверх готового native archive создаётся отдельная ZIP-обёртка F2RE Project Control.

## Сборка

```bash
./offline/build_project_control_bundle.sh <обычные параметры build_offline_bundle.sh>
```

Команда сначала полностью выполняет штатную сборку и её проверки, а затем создаёт рядом:

```text
planer-solving-<version>-project-control.f2re.zip
planer-solving-<version>-project-control.f2re.zip.sha256
```

Wrapper содержит identity `projectId=planer-solving`, `adapter=planer-solving-v1` и SHA-256 конкретного `planner-solving-offline-*.tar.gz`. Native archive не переписывается.

В Project Control ZIP перетаскивается на карточку «Борис по парам». После проверки wrapper контроллер безопасно извлекает native bundle, запускает его `verify_bundle.sh`, затем только allowlisted `install_or_update.sh --yes`. Существующие backup, миграция, health `/api/health`, автоматический rollback и `/opt/planner-solving/state/last-update.json` остаются источником истины приложения.

Для подписанного release задайте на build-машине `F2RE_RELEASE_SIGNING_KEY=/secure/release-ed25519-private.pem`. Public key переносится только в trust store Project Control на target.
