# Установка и обновление пакета 2.11

После сборки в каталоге `dist` находятся три файла:

```text
planner-solving-offline-<версия>-<система>-<архитектура>-<python>.tar.gz
planner-solving-offline-<...>.tar.gz.sha256
install-planner-solving.sh
```

Скопируйте все три файла на целевую машину и выполните:

```bash
chmod +x install-planner-solving.sh
sudo ./install-planner-solving.sh
```

Сценарий автоматически:

1. находит архив рядом с собой;
2. проверяет SHA-256;
3. распаковывает пакет во временный каталог;
4. создаёт системного пользователя `planner-solving`, если его ещё нет;
5. устанавливает приложение в `/opt/planner-solving`;
6. при обновлении сохраняет существующего пользователя службы;
7. останавливает службу и архивирует весь каталог `shared`;
8. устанавливает новый выпуск рядом со старым;
9. выполняет миграции и health-check;
10. переключает ссылку `current`;
11. запускает службу;
12. при ошибке возвращает прежний код и данные;
13. создаёт команду `planner-solving-admin` для восстановления доступа.

## Другой порт

```bash
sudo ./install-planner-solving.sh --port 8010
```

## Другой каталог

```bash
sudo ./install-planner-solving.sh --install-dir /opt/planner-solving-test
```

## Обновление

Поместите новый архив, новый `.sha256` и установщик в один каталог и снова выполните:

```bash
sudo ./install-planner-solving.sh
```

Каталог `/opt/planner-solving/shared` не удаляется и не заменяется. В нём остаются:

- SQLite с пользователями, паролями, пространствами и шаблонами;
- архив исходников истории;
- сформированные файлы;
- конфигурация;
- резервные копии.

## Проверка

```bash
systemctl status planner-solving
curl http://127.0.0.1:8001/api/health
sudo planner-solving-admin list
```

## Ручной откат

```bash
sudo /opt/planner-solving/current/offline/rollback.sh \
  --install-dir /opt/planner-solving \
  --port 8001
```

Штатный установщик также выполняет автоматический откат при неуспешном health-check.
