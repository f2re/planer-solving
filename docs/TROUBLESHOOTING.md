# Диагностика и устранение неисправностей

Документ относится к штатной установке в `/opt/planner-solving`.

## Первая команда при любой ошибке

```bash
sudo planner-solving-doctor \
  --output /tmp/planner-solving-doctor.txt
```

Дополнительно:

```bash
sudo planner-solving-python
sudo systemctl status planner-solving --no-pager -l
sudo journalctl -u planner-solving -n 160 --no-pager
curl -fsS http://127.0.0.1:8001/api/health
```

## Установщик пишет «Не найден Python»

Сначала выведите все проверенные пути:

```bash
sudo ./install-planner-solving.sh --list-python
```

Начиная с 2.14 установщик принимает файл, venv, `bin`, корень pyenv, каталог
версии pyenv, shim и каталог стандартной библиотеки. Примеры приведены в
`docs/INSTALLATION.md`.

Пакет с суффиксом `-runtime` должен содержать:

```text
python-runtime/python
python-runtime/runtime.json
```

Проверка встроенного варианта:

```bash
sudo ./install-planner-solving.sh \
  --python bundled \
  --strict-python \
  --list-python
```

Если встроенный runtime не запускается из-за версии GLIBC, используйте
локальный pyenv/venv или соберите пакет на более старой Astra Linux.

## Передан каталог, а не исполняемый файл

Версии до 2.14 пытались выполнить значение `--python` буквально и отвечали
«Это каталог». Текущая версия раскрывает каталог автоматически.

Допустимо:

```bash
--python /home/meteo/.pyenv
--python /home/meteo/.pyenv/versions/3.12.12
--python /home/meteo/.pyenv/versions/3.12.12/bin
--python /путь/к/venv
--python /путь/к/venv/bin
```

## `libpython3.12.so.1.0: cannot open shared object file`

Проверьте наличие библиотеки:

```bash
find /home/meteo/.pyenv/versions/3.12.12 \
  -name 'libpython3.12.so*' -ls
```

Проверка вручную:

```bash
LD_LIBRARY_PATH=/home/meteo/.pyenv/versions/3.12.12/lib \
/home/meteo/.pyenv/versions/3.12.12/bin/python3.12 -V
```

Штатный установщик делает такую проверку автоматически и при успехе выводит:

```text
Восстановлен путь к libpython: .../versions/3.12.12/lib
```

После установки systemd не использует этот домашний путь. Интерпретатор и
необходимые библиотеки находятся в `/opt/planner-solving/runtime`.

Не рекомендуется:

- копировать `libpython` вручную в `/usr/lib`;
- менять глобальный `/etc/ld.so.conf` ради приложения;
- запускать systemd через pyenv shim;
- добавлять `.bashrc` в unit-файл.

## Pyenv виден пользователю, но не виден через sudo

Это нормальное поведение: `sudo` меняет `HOME` и `PATH`. Внешний установщик
сохраняет исходные значения в `PLANNER_INVOKING_*`, а внутренний поиск также
проверяет `SUDO_USER` и его домашний каталог.

Запускайте внешний файл:

```bash
sudo ./install-planner-solving.sh
```

Принудительный путь:

```bash
sudo ./install-planner-solving.sh \
  --python /home/meteo/.pyenv
```

`pyenv activate` не нужен. Обычная версия CPython в pyenv не является
virtualenv, поэтому сообщение `version is not a virtualenv` не относится к
установке Planner Solving.

## Служба сообщает `ModuleNotFoundError`

Не устанавливайте пакет глобально. Проверьте реальные пути:

```bash
sudo /opt/planner-solving/state/run-service.sh --print
sudo planner-solving-python
```

Восстановление:

```bash
sudo ./install-planner-solving.sh --repair
```

Новый выпуск получает новый `.venv`; зависимости устанавливаются только из
wheelhouse и проверяются до переключения `current`.

## Служба не запускается

```bash
sudo systemctl cat planner-solving
sudo systemctl status planner-solving --no-pager -l
sudo journalctl -u planner-solving -n 160 --no-pager
sudo /opt/planner-solving/state/run-service.sh --check
```

Проверьте:

```text
/opt/planner-solving/current/.venv/bin/python
/opt/planner-solving/current/.venv/bin/python.real
/opt/planner-solving/current/.planner-runtime
/opt/planner-solving/runtime/.../python
```

## Неподходящая GLIBC у встроенного runtime

В отчёте кандидата будет ошибка вида:

```text
version `GLIBC_2.xx' not found
```

Варианты:

1. использовать исправный pyenv/venv на целевой Astra;
2. собрать пакет на Astra той же версии;
3. экспортировать runtime на самой старой поддерживаемой машине;
4. передать готовый каталог через `--use-python-runtime` при сборке.

Установщик никогда не переключит выпуск на runtime, который не прошёл
реальный запуск на целевой машине.

## Порт занят

```bash
sudo ss -ltnp | grep ':8001'
```

Другой порт:

```bash
sudo ./install-planner-solving.sh --port 8010
```

При обновлении прежний порт сохраняется автоматически.

## Ошибка прав в `/opt/planner-solving/shared`

```bash
namei -l /opt/planner-solving/shared/data
find /opt/planner-solving/shared -maxdepth 2 \
  -printf '%M %u:%g %p\n'
```

Восстановление предпочтительно выполнять установщиком:

```bash
sudo ./install-planner-solving.sh --repair
```

Ручной вариант:

```bash
sudo chown -R planner-solving:planner-solving /opt/planner-solving/shared
sudo find /opt/planner-solving/shared -type d -exec chmod 0750 {} +
sudo find /opt/planner-solving/shared -type f -exec chmod 0640 {} +
sudo systemctl restart planner-solving
```

## Обновление прервалось

Проверьте:

```bash
cat /opt/planner-solving/state/last-update.json
ls -la /opt/planner-solving/releases
ls -la /opt/planner-solving/shared/backups
```

Критическая стадия обновления защищена автоматическим откатом. Возвращаются:

- ссылка `current`;
- база и совместимое JSON-зеркало;
- конфигурация;
- unit-файл и EnvironmentFile;
- ранее активная служба.

Повтор:

```bash
sudo ./install-planner-solving.sh --repair
```

## Ручной откат

```bash
sudo /opt/planner-solving/current/offline/rollback.sh \
  --install-dir /opt/planner-solving \
  --yes
```

## Интерфейс не открывается или зависает до появления окна

В версии 2.12 вспомогательный обработчик полей пароля мог создать бесконечную
очередь `MutationObserver`. Начиная с 2.13 обработчик идемпотентен, Vue
монтируется раньше необязательных исправлений, а при ошибке появляется окно
**«Интерфейс не запустился»**.

После обновления один раз выполните принудительную перезагрузку браузера:

```text
Ctrl+Shift+R
```

Проверка кэша:

```bash
curl -I http://127.0.0.1:8001/
curl -I http://127.0.0.1:8001/assets/app.js
```

Для HTML ожидается `Cache-Control: no-store`, для JavaScript — обязательная
перепроверка.

## SQLite повреждена или имеет неверную схему

```bash
sudo -u planner-solving \
  /opt/planner-solving/current/.venv/bin/python \
  -m tools.healthcheck \
  --app-root /opt/planner-solving/current \
  --data-dir /opt/planner-solving/shared/data \
  --json
```

Не удаляйте базу до проверки резервных копий:

```bash
ls -lt /opt/planner-solving/shared/backups
```
