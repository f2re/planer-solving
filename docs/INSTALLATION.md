# Штатная установка и автономное обновление

Начиная с версии 2.13 основной способ эксплуатации — версионированная установка в:

```text
/opt/planner-solving
```

Приложение, виртуальное окружение и постоянные данные разделены. Обновление не записывает новый код поверх работающего выпуска.

## Состав пакета

После сборки в `dist` находятся:

```text
planner-solving-offline-<версия>-<система>-<архитектура>-<python>.tar.gz
planner-solving-offline-<...>.tar.gz.sha256
install-planner-solving.sh
README-INSTALL.txt
```

Для установки на автономной машине скопируйте все четыре файла в один каталог.

## Установка одной командой

```bash
chmod +x install-planner-solving.sh
sudo ./install-planner-solving.sh
```

По умолчанию сценарий:

- проверяет SHA-256 архива;
- проверяет внутренний manifest и каждый файл;
- определяет точную версию Python пакета;
- создаёт системного пользователя `planner-solving`;
- устанавливает выпуск в `/opt/planner-solving/releases`;
- создаёт отдельный `.venv` выпуска;
- устанавливает библиотеки только из включённого `wheelhouse`;
- проверяет импорты от имени пользователя службы;
- создаёт резервную копию постоянных данных;
- выполняет миграции и проверку базы;
- атомарно переключает ссылку `current`;
- создаёт и запускает `planner-solving.service`;
- проверяет HTTP-адрес `/api/health`;
- автоматически возвращает прежнее состояние при ошибке;
- сохраняет диагностический отчёт.

## Требования к Python

Версия указана в имени пакета. Пример:

```text
...-py311.tar.gz
```

означает Python 3.11. Нужен интерпретатор той же основной и дополнительной версии и той же архитектуры.

Обычная установка:

```bash
sudo ./install-planner-solving.sh \
  --python /usr/bin/python3.11
```

Модуль `venv` должен быть доступен. На Debian-подобных системах он может поставляться отдельным пакетом соответствующей версии Python.

Автономный архив содержит все Python-колёса приложения, поэтому сеть на целевой машине не требуется.

## Выбор порта и адреса

```bash
sudo ./install-planner-solving.sh \
  --host 0.0.0.0 \
  --port 8010
```

Для локального доступа только с сервера:

```bash
sudo ./install-planner-solving.sh \
  --host 127.0.0.1
```

Параметры сохраняются в:

```text
/etc/default/planner-solving
```

## Обновление

Поместите рядом новый архив, новый `.sha256` и новый установщик, затем повторите:

```bash
sudo ./install-planner-solving.sh
```

Постоянный каталог:

```text
/opt/planner-solving/shared
```

не удаляется и не заменяется. В нём сохраняются:

- SQLite;
- пользователи и хэши паролей;
- пространства;
- преподаватели;
- шаблоны и их версии;
- история запусков;
- архивы исходных файлов;
- сформированные документы;
- конфигурация;
- резервные копии.

## Почему systemd больше не ищет библиотеки самостоятельно

Unit-файл запускает стабильный сценарий:

```text
/opt/planner-solving/state/run-service.sh
```

Сценарий разрешает активный выпуск через `current` и использует абсолютный путь:

```text
/opt/planner-solving/current/.venv/bin/python
```

Перед запуском веб-сервера проверяются:

- Python и его версия;
- наличие venv;
- импорты `uvicorn`, `fastapi`, `pydantic`, `openpyxl`, `pandas`, `ortools` и `multipart`;
- файлы приложения;
- права записи в постоянные каталоги;
- создание FastAPI-приложения;
- состояние базы и схемы.

Интерактивный `PATH`, `.bashrc`, `pyenv init` и пользовательский `site-packages` не участвуют в работе службы.

## Управление службой

```bash
sudo systemctl status planner-solving --no-pager -l
sudo systemctl restart planner-solving
sudo systemctl stop planner-solving
sudo systemctl start planner-solving
sudo journalctl -u planner-solving -n 100 --no-pager
```

Проверка:

```bash
curl -fsS http://127.0.0.1:8001/api/health
sudo /opt/planner-solving/state/run-service.sh --check
```

## Диагностика

```bash
sudo planner-solving-doctor
```

Отчёт после установки:

```text
/opt/planner-solving/state/last-doctor-report.txt
```

Подробное руководство: `docs/TROUBLESHOOTING.md`.

## Управление пользователями

```bash
sudo planner-solving-admin list
sudo planner-solving-admin reset-password admin
sudo planner-solving-admin reset-password admin --empty
```

## Установка без systemd

Для тестового или пользовательского каталога:

```bash
bash <распакованный-пакет>/install_or_update.sh \
  --install-dir "$HOME/.local/opt/planner-solving" \
  --service-user "$(id -un)" \
  --python "$(command -v python3)" \
  --no-systemd \
  --yes
```

Запуск:

```bash
$HOME/.local/opt/planner-solving/state/run.sh
```

Штатная серверная эксплуатация всё же должна использовать `/opt` и systemd.

## Контроль целостности

Файл `.sha256` обязателен. Установка без него прекращается.

Аварийное разрешение неподписанного архива существует только для контролируемого локального контура:

```bash
sudo ./install-planner-solving.sh --allow-unsigned
```

Оно не отключает проверку внутреннего manifest.

## Хранение выпусков

По умолчанию остаются три последних выпуска:

```bash
sudo ./install-planner-solving.sh --keep-releases 5
```

Текущий и предыдущий выпуски не удаляются во время очистки.

## Откат

```bash
sudo /opt/planner-solving/current/offline/rollback.sh \
  --install-dir /opt/planner-solving \
  --yes
```

Откат возвращает код и данные к состоянию перед последним обновлением и проверяет службу после переключения.

## Перенос прежней установки

Внутренний установщик поддерживает перенос:

```bash
sudo <распакованный-пакет>/install_or_update.sh \
  --install-dir /opt/planner-solving \
  --legacy-dir /путь/к/старой/установке \
  --service-user planner-solving \
  --yes
```

Перед переносом сохраните отдельную резервную копию старого каталога.

## Размещение файлов

```text
/opt/planner-solving/
├── current -> releases/<версия>-<дата>/
├── releases/
│   └── <версия>-<дата>/
│       ├── .venv/
│       ├── src/
│       ├── web/
│       └── tools/
├── shared/
│   ├── data/
│   ├── input/
│   ├── output/
│   ├── backups/
│   ├── home/
│   └── cache/
└── state/
    ├── run-service.sh
    ├── run.sh
    ├── doctor.sh
    ├── admin.sh
    ├── last-update.json
    └── history.jsonl
```
