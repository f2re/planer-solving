# Штатная установка и автономное обновление

Начиная с версии 2.14 основной комплект содержит не только приложение и
Python-колёса, но и проверяемый управляемый Python runtime. Установка по
умолчанию выполняется в:

```text
/opt/planner-solving
```

Код, виртуальное окружение, Python runtime и постоянные данные разделены.
Обновление создаёт новый выпуск рядом с работающим и переключает его только
после всех проверок.

## Состав автономного комплекта

```text
planner-solving-offline-<версия>-<система>-<архитектура>-py<версия>-runtime.tar.gz
planner-solving-offline-<...>.tar.gz.sha256
install-planner-solving.sh
README-INSTALL.txt
```

Скопируйте на целевой компьютер все четыре файла.

## Установка и обновление одной командой

```bash
chmod +x install-planner-solving.sh
sudo ./install-planner-solving.sh
```

Эта же команда используется для последующих обновлений. Существующие порт,
адрес, пользователь службы и постоянные данные сохраняются, если новые
значения не переданы явно.

## Что установщик делает автоматически

1. Проверяет внешний SHA-256 архива.
2. Проверяет пути внутри архива до распаковки.
3. Проверяет внутренний `SHA256SUMS` и `manifest.json`.
4. Определяет точную версию и архитектуру Python, требуемую wheelhouse.
5. Находит все доступные Python и виртуальные окружения.
6. При необходимости восстанавливает путь к `libpython*.so` у pyenv.
7. Копирует рабочий Python в управляемый runtime внутри `/opt`.
8. Создаёт новый отдельный `.venv` выпуска.
9. Устанавливает библиотеки только из автономного wheelhouse.
10. Проверяет импорты от имени пользователя systemd-службы.
11. Останавливает прежнюю службу и создаёт резервную копию данных.
12. Выполняет миграции и полную проверку приложения.
13. Атомарно переключает ссылку `current`.
14. Обновляет unit-файл systemd и запускает службу.
15. Проверяет `/api/health`.
16. При любой ошибке возвращает код, данные, unit-файл и прежнюю службу.

## Почему системный Python 3.7 больше не блокирует установку

Astra Linux может иметь только `/usr/bin/python3.7`, тогда как wheelhouse
собран, например, для CPython 3.12. Раньше такой пакет невозможно было
установить без заранее исправного Python 3.12.

Пакет с суффиксом `-runtime` содержит CPython той же дополнительной версии,
что и wheelhouse. Если он запускается на целевой машине, системный Python
вообще не используется.

Если встроенный runtime несовместим с библиотеками целевой ОС, установщик
переходит к локальным вариантам: существующему venv, pyenv, asdf, conda,
`/usr`, `/usr/local`, `/opt` и дополнительным каталогам поиска.

## Порядок поиска Python

Установщик проверяет варианты в следующем порядке:

1. Явно переданный `--python`.
2. Текущий venv Planner Solving.
3. Venv предыдущих выпусков.
4. Уже установленные управляемые runtime.
5. Активный `VIRTUAL_ENV` пользователя, вызвавшего `sudo`.
6. Его `pyenv`, включая все версии и shims.
7. Venv, pyenv, asdf и conda других локальных пользователей.
8. `/usr/bin`, `/usr/local/bin`, `/opt/python*` и обычный `PATH`.
9. Встроенный Python runtime пакета.

Каждый кандидат реально запускается и должен:

- иметь требуемую основную и дополнительную версию;
- импортировать `venv`, `ensurepip`, `ssl` и `sqlite3`;
- соответствовать архитектуре пакета;
- быть доступным указанному пользователю.

## Какие значения принимает `--python`

Можно указать не только исполняемый файл:

```bash
sudo ./install-planner-solving.sh --python /usr/bin/python3.12
sudo ./install-planner-solving.sh --python /путь/к/venv
sudo ./install-planner-solving.sh --python /путь/к/venv/bin
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv/bin/pyenv
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv/versions/3.12.12
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv/versions/3.12.12/bin
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv/shims/python3.12
sudo ./install-planner-solving.sh --python /home/meteo/.pyenv/versions/3.12.12/lib/python3.12
sudo ./install-planner-solving.sh --python bundled
```

Каталоги нормализуются автоматически. Передача каталога больше не приводит к
попытке выполнить его как программу.

## Pyenv и отсутствующий `libpython`

Типичная ошибка:

```text
error while loading shared libraries: libpython3.12.so.1.0:
cannot open shared object file
```

Если `libpython3.12.so.1.0` находится рядом с версией pyenv, установщик:

1. находит каталог `.../.pyenv/versions/3.12.12/lib`;
2. повторяет проверку с временным `LD_LIBRARY_PATH`;
3. экспортирует рабочий интерпретатор, stdlib и необходимые библиотеки;
4. переносит runtime в `/opt/planner-solving/runtime`;
5. создаёт новый venv, который больше не зависит от `/home/meteo` и pyenv.

Изменять глобальный `ld.so.conf`, копировать библиотеки в `/usr/lib` или
активировать pyenv для systemd не требуется.

## Просмотр найденных Python и venv

До установки:

```bash
sudo ./install-planner-solving.sh --list-python
```

После установки:

```bash
sudo planner-solving-python
```

Команда выводит:

- путь каждого кандидата;
- источник: venv, pyenv, system, `/opt` и т.д.;
- версию;
- причину отказа;
- восстановленный `LD_LIBRARY_PATH`;
- пользователя, от имени которого выполнялась проверка.

## Строгий выбор Python

По умолчанию неудачный `--python` не останавливает поиск: установщик пробует
остальные варианты. Для запрета резервного выбора:

```bash
sudo ./install-planner-solving.sh \
  --python /нужный/путь \
  --strict-python
```

## Дополнительные каталоги поиска

```bash
sudo ./install-planner-solving.sh \
  --python-search-root /srv/python \
  --python-search-root /opt/local-venvs
```

Параметр можно повторять.

## Восстановление повреждённой установки

```bash
sudo ./install-planner-solving.sh --repair
```

Режим заново создаёт:

- выпуск приложения;
- `.venv`;
- pth-файл приложения;
- стабильные сценарии запуска;
- systemd unit и `/etc/default/planner-solving`.

Каталог `shared` сохраняется.

## Выбор порта, адреса и числа процессов

```bash
sudo ./install-planner-solving.sh \
  --host 0.0.0.0 \
  --port 8010 \
  --workers 1
```

Значения сохраняются в:

```text
/etc/default/planner-solving
```

При обычном обновлении существующие значения автоматически используются
снова.

## Размещение файлов

```text
/opt/planner-solving/
├── current -> releases/<версия>-<дата>/
├── releases/
│   └── <версия>-<дата>/
│       ├── .venv/
│       ├── .planner-runtime
│       ├── src/
│       ├── web/
│       └── tools/
├── runtime/
│   └── python-<версия>-<архитектура>-<идентификатор>/
│       ├── python
│       ├── runtime.json
│       └── prefix/
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
    ├── python-info.sh
    ├── admin.sh
    ├── last-update.json
    └── history.jsonl
```

## Systemd

Служба запускает стабильный путь:

```text
/opt/planner-solving/state/run-service.sh
```

Он разрешает активный выпуск через `current` и использует:

```text
/opt/planner-solving/current/.venv/bin/python
```

Перед стартом выполняются проверка runtime, venv, импортов, прав записи,
FastAPI-приложения и SQLite. `pip install` при запуске службы не выполняется.

```bash
sudo systemctl status planner-solving --no-pager -l
sudo systemctl restart planner-solving
sudo journalctl -u planner-solving -n 120 --no-pager
curl -fsS http://127.0.0.1:8001/api/health
```

## Диагностика

```bash
sudo planner-solving-doctor
sudo planner-solving-doctor --output /tmp/planner-solving-doctor.txt
```

## Откат

```bash
sudo /opt/planner-solving/current/offline/rollback.sh \
  --install-dir /opt/planner-solving \
  --yes
```

Перед откатом создаётся дополнительная резервная копия. Если предыдущий
выпуск не проходит проверку, состояние до попытки отката возвращается.

## Сборка пакета

```bash
PYTHON_BIN=/usr/bin/python3.12 \
bash offline/build_offline_bundle.sh \
  --output dist \
  --python /usr/bin/python3.12
```

По умолчанию runtime включается. Облегчённый пакет только с wheelhouse:

```bash
bash offline/build_offline_bundle.sh \
  --output dist \
  --python /usr/bin/python3.12 \
  --without-python-runtime
```

Для Astra Linux наиболее переносимый вариант получается, если runtime
экспортирован на Astra той же или более старой версии, чем целевые машины:

```bash
bash offline/build_offline_bundle.sh \
  --output dist \
  --python /путь/к/python3.12 \
  --runtime-python /путь/к/python3.12
```

Можно заранее подготовить runtime и передать каталог через
`--use-python-runtime`. Независимо от способа сборки установщик обязательно
пробует runtime на целевой машине до переключения выпуска.
