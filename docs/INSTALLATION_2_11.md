# Установка и обновление

Этот документ сохранён как совместимая ссылка для выпусков 2.11–2.12.

Актуальная штатная схема версии 2.13 и новее описана в:

- [`INSTALLATION.md`](INSTALLATION.md) — установка и автономное обновление в `/opt`;
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — диагностика интерфейса, Python, systemd, прав, портов и базы.

Основная команда:

```bash
chmod +x install-planner-solving.sh
sudo ./install-planner-solving.sh
```

После установки:

```bash
sudo planner-solving-doctor
systemctl status planner-solving --no-pager -l
curl -fsS http://127.0.0.1:8001/api/health
```

Прежние ручные варианты запуска unit-файла через системный `python3` больше не рекомендуются. Служба должна использовать стабильный запускатель `/opt/planner-solving/state/run-service.sh` и venv активного выпуска.
