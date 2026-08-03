# Диагностика и устранение неисправностей

Документ относится к штатной установке в `/opt/planner-solving` и службе `planner-solving.service`.

## Быстрая проверка

Выполните одну команду:

```bash
sudo planner-solving-doctor
```

Сохранить отчёт в файл:

```bash
sudo planner-solving-doctor \
  --output /tmp/planner-solving-doctor.txt
```

Дополнительные команды:

```bash
systemctl status planner-solving --no-pager -l
journalctl -u planner-solving -n 120 --no-pager
curl -fsS http://127.0.0.1:8001/api/health
```

Начинайте с первого раздела отчёта, в котором код возврата отличается от нуля.

## Интерфейс не открывается или браузер зависает до появления окна

### Исправленная причина

В версии 2.12 вспомогательный обработчик полей пароля мог создать бесконечную очередь `MutationObserver`: обработчик удалял `minlength`, затем свойством JavaScript создавал этот же атрибут снова. Очередь микрозадач блокировала основной поток ещё до запуска Vue.

Начиная с версии 2.13:

- обработчик не создаёт удалённый атрибут повторно;
- повторная установка обработчика безопасна;
- Vue запускается раньше необязательных исправлений формы;
- через 10 секунд появляется читаемое окно ошибки запуска вместо бесконечного пустого экрана;
- HTML не кэшируется, JavaScript и CSS обязательно перепроверяются после обновления.

### Что сделать на рабочем месте

1. Обновите установленный пакет.
2. Откройте страницу с принудительной перезагрузкой: `Ctrl+Shift+R` или `Ctrl+F5`.
3. Закройте старые вкладки Planner Solving.
4. Проверьте файлы напрямую:

```bash
curl -I http://127.0.0.1:8001/
curl -I http://127.0.0.1:8001/assets/app.js
curl -fsS http://127.0.0.1:8001/assets/app.js | head
```

Для `/` должен присутствовать `Cache-Control: no-store`, для `/assets/app.js` — `no-cache, must-revalidate`.

Если появилось окно **«Интерфейс не запустился»**, скопируйте текст ошибки. Оно указывает конкретный модуль, который браузер не смог загрузить или выполнить.

## Служба не запускается

Проверьте:

```bash
sudo systemctl cat planner-solving
sudo systemctl status planner-solving --no-pager -l
sudo journalctl -u planner-solving -n 120 --no-pager
sudo /opt/planner-solving/state/run-service.sh --print
sudo /opt/planner-solving/state/run-service.sh --check
```

Штатный unit-файл запускает не системный `python`, а стабильный сценарий:

```text
/opt/planner-solving/state/run-service.sh
```

Он каждый раз разрешает текущий выпуск через:

```text
/opt/planner-solving/current
```

и использует только:

```text
/opt/planner-solving/current/.venv/bin/python
```

Поэтому служба не зависит от интерактивного `PATH`, `pyenv init`, `.bashrc`, пользовательских `site-packages` или каталога, из которого была выполнена установка.

## `ModuleNotFoundError`, `No module named uvicorn`, `fastapi`, `openpyxl`

Не устанавливайте библиотеки глобально и не добавляйте случайные пути в `PYTHONPATH` unit-файла.

Правильное восстановление:

```bash
sudo ./install-planner-solving.sh
```

Установщик заново создаст отдельный venv выпуска и установит зависимости из включённого `wheelhouse` без доступа к сети.

Проверка импортов:

```bash
sudo -u planner-solving \
  /opt/planner-solving/current/.venv/bin/python \
  -m tools.service_preflight \
  --app-root /opt/planner-solving/current \
  --shared-dir /opt/planner-solving/shared
```

## Не найден подходящий Python

Имя архива содержит версию Python, например:

```text
planner-solving-offline-2.13.0-linux-x86_64-py311.tar.gz
```

Пакет `py311` требует Python 3.11 той же архитектуры. Колёса библиотек уже находятся в архиве, но сам интерпретатор в обычный пакет не включается.

Предпочтительные пути:

```text
/usr/bin/python3.11
/usr/local/bin/python3.11
/opt/python3.11/bin/python3.11
```

Явный запуск:

```bash
sudo ./install-planner-solving.sh \
  --python /usr/bin/python3.11
```

Для Debian/Astra обычно нужен также модуль создания окружений, например пакет `python3.11-venv` или соответствующий пакет версии Python в используемом репозитории ОС.

Не используйте для systemd интерпретатор из закрытого домашнего каталога обычного пользователя. Системный пользователь `planner-solving` может не иметь права прохода по `/home/...`, даже если root создал venv без ошибки.

## `Permission denied` в `/opt/planner-solving/shared`

Штатная установка назначает владельцем данных пользователя службы. Для проверки:

```bash
namei -l /opt/planner-solving/shared/data
find /opt/planner-solving/shared -maxdepth 2 \
  -printf '%M %u:%g %p\n'
```

Восстановление прав:

```bash
sudo chown -R planner-solving:planner-solving \
  /opt/planner-solving/shared
sudo find /opt/planner-solving/shared -type d -exec chmod 0750 {} +
sudo find /opt/planner-solving/shared -type f -exec chmod 0640 {} +
sudo systemctl restart planner-solving
```

Повторный установщик выполняет это автоматически и безопаснее ручной правки.

## Порт уже занят

```bash
sudo ss -ltnp | grep ':8001'
```

Установить на другом порту:

```bash
sudo ./install-planner-solving.sh --port 8010
```

Порт сохраняется в:

```text
/etc/default/planner-solving
```

После ручной правки:

```bash
sudo systemctl daemon-reload
sudo systemctl restart planner-solving
```

## Служба активна, но `/api/health` не отвечает

Проверьте адрес и порт:

```bash
cat /etc/default/planner-solving
sudo ss -ltnp
curl -v --max-time 5 http://127.0.0.1:8001/api/health
```

Затем запустите проверку без веб-сервера:

```bash
sudo -u planner-solving \
  env PLANNER_INSTALL_ROOT=/opt/planner-solving \
  PLANNER_PORT=8001 \
  /opt/planner-solving/state/run-service.sh --check
```

Если эта команда проходит, а systemd — нет, сравните окружение и ограничения unit-файла через `systemctl cat planner-solving`.

## Повреждена или недоступна SQLite

```bash
sudo -u planner-solving \
  /opt/planner-solving/current/.venv/bin/python \
  -m tools.healthcheck \
  --app-root /opt/planner-solving/current \
  --data-dir /opt/planner-solving/shared/data \
  --json
```

Не удаляйте файлы:

```text
planner-solving.sqlite3
planner-solving.sqlite3-wal
planner-solving.sqlite3-shm
```

во время работающей службы. Сначала остановите её:

```bash
sudo systemctl stop planner-solving
```

Перед каждым обновлением установщик создаёт архив в:

```text
/opt/planner-solving/shared/backups
```

## Обновление не завершилось

Установщик действует по схеме:

1. проверка SHA-256;
2. проверка manifest и всех файлов;
3. создание нового каталога выпуска;
4. создание venv и установка колёс;
5. запуск предварительной проверки от имени пользователя службы;
6. резервная копия данных;
7. миграция и полная проверка;
8. атомарное переключение `current`;
9. запуск systemd и HTTP-проверка;
10. автоматический возврат прежнего выпуска и данных при ошибке.

Посмотрите:

```bash
cat /opt/planner-solving/state/last-update.json
tail -n 20 /opt/planner-solving/state/history.jsonl
ls -lt /opt/planner-solving/shared/backups
```

После устранения причины просто повторите установку тем же пакетом.

## Ручной откат

```bash
sudo /opt/planner-solving/current/offline/rollback.sh \
  --install-dir /opt/planner-solving \
  --yes
```

Откат также:

- создаёт аварийную копию текущих данных;
- проверяет venv предыдущего выпуска;
- выполняет `run-service.sh --check`;
- запускает службу;
- проверяет `/api/health`;
- возвращает состояние до попытки отката, если проверка не прошла.

## Полная переустановка без потери данных

Не удаляйте `/opt/planner-solving/shared`.

```bash
sudo systemctl stop planner-solving
sudo ./install-planner-solving.sh
sudo systemctl status planner-solving --no-pager -l
```

Код выпусков находится в `releases`, а постоянные данные — отдельно в `shared`. Повторная установка не заменяет базу, пользователей, шаблоны, историю и сформированные файлы.

## Структура штатной установки

```text
/opt/planner-solving/
├── current -> releases/2.13.0-...
├── releases/
│   ├── 2.13.0-.../
│   │   └── .venv/
│   └── предыдущий-выпуск/
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

## Что не следует делать

- Не добавляйте `pip install` в `ExecStartPre` или `ExecStart`.
- Не запускайте службу через `python3` без абсолютного пути к venv.
- Не используйте библиотеки из пользовательского `~/.local/lib/python...`.
- Не копируйте новый код поверх активного выпуска.
- Не заменяйте каталог `shared` при обновлении.
- Не отключайте проверку SHA-256, кроме контролируемой аварийной установки.
- Не удаляйте предыдущий выпуск до успешной проверки нового.
