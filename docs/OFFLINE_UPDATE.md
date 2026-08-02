# Офлайн-установка и обновление Planner Solving

## Общая схема

Полностью отключённая машина не может скачать обновление самостоятельно. Обновление готовится на машине с интернетом, переносится на USB-носителе или через разрешённый файловый шлюз и устанавливается локально.

Офлайн-пакет содержит:

- исходный код конкретной версии;
- все рабочие Python-зависимости в `wheelhouse`;
- манифест версии, Python, платформы и архитектуры;
- SHA-256 каждого файла;
- установщик, обновление и откат;
- миграции данных и локальную проверку работоспособности.

Рабочая SQLite-база, преподаватели, шаблоны и сформированные расписания в пакет не включаются.

## Требования к целевой машине

- Linux с архитектурой, совпадающей со сборочной машиной;
- Python той же основной и дополнительной версии, что указана в пакете; рекомендуется Python 3.11;
- модуль `venv`;
- `bash`, `tar` и стандартные системные утилиты;
- systemd — только для установки как службы.

Для Astra Linux пакет рекомендуется собирать на машине с той же версией ОС либо на самой старой совместимой системе. Это снижает риск несовместимости glibc у бинарных Python-колёс.

## Получение пакета на машине с интернетом

### Локальная сборка

```bash
cd planer-solving
git checkout main
git pull
python3.11 -m pip install --upgrade pip
bash offline/build_offline_bundle.sh --output dist
```

Будут созданы:

```text
dist/planner-solving-offline-<версия>-linux-<архитектура>-py311.tar.gz
dist/planner-solving-offline-<версия>-linux-<архитектура>-py311.tar.gz.sha256
```

Проверка:

```bash
cd dist
sha256sum -c *.tar.gz.sha256
```

### GitHub Actions

В разделе **Actions → Offline bundle → Run workflow** запускается сборка Linux x86_64 / Python 3.11. После завершения скачивается артефакт `planner-solving-offline-linux-x86_64-py311`.

Сборка GitHub Actions создаётся на Ubuntu 22.04. Для Astra Linux надёжнее локальная сборка на совместимой машине.

## Перенос в закрытый контур

На носитель копируются архив и `.sha256`. На целевой машине:

```bash
sha256sum -c planner-solving-offline-*.tar.gz.sha256
tar -xzf planner-solving-offline-*.tar.gz
cd planner-solving-offline-*
python3 verify_bundle.py .
```

Контрольную сумму желательно передавать по отдельному доверенному каналу.

## Первая установка

```bash
sudo bash install_or_update.sh \
  --install-dir /opt/planner-solving \
  --service-user planner \
  --port 8001
```

Для переноса прежней установки из Git-репозитория:

```bash
sudo bash install_or_update.sh \
  --install-dir /opt/planner-solving \
  --legacy-dir /home/user/planer-solving \
  --service-user user \
  --port 8001
```

Из старой установки переносятся:

- каталог `data`, включая существующую SQLite-базу либо `workspaces.json`;
- `teachers.json`;
- `config.json`;
- существующие файлы `output`.

Если SQLite ещё нет, версия 2.5 автоматически создаст её из проверенного `workspaces.json`. Исходный каталог не удаляется.

## Последующие обновления

```bash
sudo bash install_or_update.sh \
  --install-dir /opt/planner-solving \
  --service-user planner \
  --port 8001 \
  --yes
```

Установщик:

1. проверяет контрольные суммы;
2. проверяет Python и архитектуру;
3. создаёт неизменяемый выпуск в `releases`;
4. устанавливает зависимости только из `wheelhouse`;
5. останавливает службу;
6. архивирует весь каталог общих данных после остановки процесса;
7. применяет JSON-миграции;
8. создаёт или проверяет SQLite и выполняет `PRAGMA quick_check`;
9. атомарно переключает ссылку `current`;
10. запускает службу и опрашивает `/api/health`;
11. при ошибке возвращает прежний выпуск и согласованную копию данных.

Остановка службы перед архивированием обязательна: в режиме WAL согласованное состояние может находиться одновременно в основном SQLite-файле и `-wal`.

## Структура установленной системы

```text
/opt/planner-solving/
  current -> releases/2.5.0-20260802-120000
  releases/
    2.4.0-...
    2.5.0-...
  shared/
    data/
      planner-solving.sqlite3
      planner-solving.sqlite3-wal  # существует только во время работы
      planner-solving.sqlite3-shm  # существует только во время работы
      workspaces.json              # совместимое зеркало
    teachers.json                  # зеркало основного пространства
    config.json
    input/
    output/
    backups/
  state/
    run.sh
    last-update.json
    history.jsonl
```

Код выпуска не изменяется. Все рабочие данные находятся в `shared`.

## Откат

```bash
sudo bash rollback.sh \
  --install-dir /opt/planner-solving \
  --port 8001
```

Откат возвращает предыдущий код и архив данных, созданный непосредственно перед обновлением. Перед откатом создаётся аварийная копия текущего состояния. Если откат завершится ошибкой, установщик возвращает состояние до попытки отката.

Изменения, внесённые после обновления, не переносятся автоматически в старую схему. Их аварийная копия сохраняется в `shared/backups`.

## Работа без systemd

```bash
bash install_or_update.sh \
  --install-dir "$HOME/planner-solving" \
  --no-systemd

"$HOME/planner-solving/state/run.sh"
```

В этом режиме установщик проверяет импорт, JSON-зеркало и SQLite, но не выполняет HTTP-проверку службы автоматически.

## Проверка установленной системы

```bash
cd /opt/planner-solving/current
sudo -u planner .venv/bin/python -m tools.healthcheck \
  --app-root . \
  --data-dir /opt/planner-solving/shared/data

curl http://127.0.0.1:8001/api/health
```

Дополнительная проверка SQLite:

```bash
sqlite3 /opt/planner-solving/shared/data/planner-solving.sqlite3 \
  'PRAGMA quick_check; PRAGMA user_version;'
```

Утилита `sqlite3` необязательна для работы приложения.

## Резервное копирование

Рекомендуется сохранять весь каталог:

```text
/opt/planner-solving/shared
```

Минимально обязательны:

- весь `shared/data`, а не только основной SQLite-файл;
- `shared/teachers.json`;
- `shared/config.json`.

Для ручной копии работающей системы предварительно остановите службу либо используйте SQLite backup API. Нельзя копировать только `planner-solving.sqlite3`, игнорируя активный `-wal`.

Каталог `output` можно хранить по собственной политике.

## Ограничения

- Бинарные колёса нельзя без проверки переносить между архитектурами и версиями Python.
- Сборка GitHub Actions не гарантирует совместимость со всеми версиями Astra Linux.
- Откат к версии, не понимающей текущую схему, выполняется только вместе с резервной копией данных.
- На время миграции допускается один активный процесс; установщик сам останавливает известные службы.
- SQLite не следует размещать на NFS/SMB. Для нескольких серверных узлов потребуется сетевая СУБД.

Подробности о базе: [`SQLITE_STORAGE.md`](SQLITE_STORAGE.md).
