# Новые API версии 2.9

- `/api/auth/*` — первичная настройка, вход, пользователи;
- `/api/workspaces/{id}/imports/preview` — предварительный импорт;
- `/api/imports/{id}/evaluate|commit|report.csv` — проверка и запись;
- `/api/workspaces/{id}/templates/{template}/revisions` — история шаблона;
- `/api/template-revisions/compare` — сравнение;
- `/api/workspaces/{id}/templates/{template}/rollback` — откат;
- `/api/workspaces/{id}/templates/learn` — подтверждаемое обучение;
- `/api/workspaces/{id}/format-rules` — правила форматов;
- `/api/workspaces/{id}/history` — запуски;
- `/api/history/{run}` — детали и повтор;
- `/api/history/artifacts/{id}` — сохранённые результаты;
- `/api/audit` — журнал действий администратора.

Изменяющие запросы после входа требуют заголовок `X-CSRF-Token`.
