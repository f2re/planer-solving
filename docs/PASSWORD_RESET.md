# Пароли и восстановление доступа

## Политика паролей

«Борис по парам» не задаёт требований к длине и сложности пароля. Допустимы:

- короткий пароль;
- длинная фраза;
- пустой пароль.

Пароль независимо от длины хранится только как PBKDF2-HMAC-SHA256 с индивидуальной солью. Пустой пароль означает, что пользователь вводит только логин и отправляет форму.

Для доступной из сети установки рекомендуется использовать непустые пароли и HTTPS. Отсутствие требований сделано для автономных локальных контуров и не заменяет организационную политику безопасности.

## Сброс в интерфейсе

Администратор открывает:

```text
Центр операций → Пользователи → Изменить → Сбросить пароль
```

Пароль становится пустым, а все действующие сеансы пользователя закрываются.

## Сброс командой после штатной установки

Показать пользователей:

```bash
sudo planner-solving-admin list
```

Интерактивно задать новый пароль:

```bash
sudo planner-solving-admin reset-password admin
```

Установить пустой пароль:

```bash
sudo planner-solving-admin reset-password admin --empty
```

Изменить роль:

```bash
sudo planner-solving-admin set-role operator admin
```

Включить отключённого пользователя:

```bash
sudo planner-solving-admin unlock admin
```

Создать нового администратора:

```bash
sudo planner-solving-admin create-admin \
  --username reserve-admin \
  --display-name "Резервный администратор" \
  --empty
```

## Запуск команды без системной ссылки

```bash
sudo /opt/planner-solving/state/admin.sh list
sudo /opt/planner-solving/state/admin.sh reset-password admin --empty
```

Либо напрямую:

```bash
cd /opt/planner-solving/current
sudo -u planner-solving .venv/bin/python -m tools.user_admin \
  --data-dir /opt/planner-solving/shared/data \
  --legacy-teachers /opt/planner-solving/shared/teachers.json \
  reset-password admin --empty
```

## Что сохраняется при обновлении

Пользователи, хэши паролей, роли и сеансы находятся в:

```text
/opt/planner-solving/shared/data/planner-solving.sqlite3
```

Новый выпуск устанавливается в отдельный каталог `releases`. Каталог `shared` не заменяется. Перед обновлением создаётся полная резервная копия, поэтому пароль и данные не уничтожаются при штатном обновлении или автоматическом откате.
