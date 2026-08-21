# Борис по парам 2.27.0 — исправление визуальной системы и TrueColor ассеты

Дата: 2026-08-21

## Основные изменения выпуска

В версии **2.27.0** устранена проблема пережатия и деформации графических материалов на главной странице, улучшена типографика и зафиксирован строгий контракт обязательного версионирования для всех агентов проекта.

---

### 1. Визуальная система и ассеты высокого разрешения (TrueColor PNG)

- Пережатые 8-битные 24-цветные растры заменены на качественные **TrueColor PNG (24-bit RGB / 32-bit RGBA)** с поддержкой HiDPI/Retina (`@2x`):
  - `web/frontend/assets/brand/hero-schedule.png` (1200×675 px);
  - `web/frontend/assets/brand/organized-flow.png` (1120×700 px);
  - `web/frontend/assets/brand/app-icon-128.png` (128×128 px).
- Устранены постеризация, артефакты сжатия и шум на таблицах расписания и тексте интерфейса.
- Сохранены строгие офлайн-контракты и валидация PNG-чанков (`IHDR`, `IDAT`, `IEND`, CRC32) в тестах `test_visual_brand.py`.

---

### 2. Устранение CSS-деформаций и адаптивность

- **Удалена 3D-перспектива:** Убрано свойство `transform: perspective(1200px) rotateY(-2deg) rotateX(1deg)` в `brand-refresh.css`, вызывавшее субпиксельное размытие и геометрические искажения растра.
- **Устранено принудительное растяжение:** Из `interface-clean.css` удалены `align-self: stretch`, `height: 100%`, `min-height: 350px` и `max-height: 510px`, растягивавшие карточку по высоте колонки текста и приводившие к нежелательной обрезке через `object-fit: cover`.
- **Естественное масштабирование:** Зафиксировано свойство `aspect-ratio: 16 / 9; width: 100%; height: auto; object-fit: cover; align-self: center;`.
- **Типографика и контраст:** Увеличен размер служебного текста верхней панели до 11–12px с повышенной контрастностью по стандарту WCAG AA (`#334155`, `#4a5568`).

---

### 3. Контракты агентов (Agent Versioning Discipline)

- Во все конфигурации агентов (`.gemini/agents/orchestrator.md`, `.gemini/agents/frontend-developer.md`, `.gemini/agents/developer.md`, `.gemini/agents/backend-developer.md`, `.gemini/agents/tester.md`) добавлен обязательный регламент:
  1. Инкремент версии в `VERSION` при любых релизных изменениях.
  2. Актуализация документации и списков изменений.
  3. Обязательный прогон полного набора тестов (`pytest`).
  4. Пересборка и верификация автономного бандла (`./offline/build_offline_bundle.sh`).
  5. Фиксация коммитов и пуш в ветку `main`.

---

### 4. Автономное развертывание

- Сформирован обновленный офлайн-дистрибутив **2.27.0**:
  - `dist/planner-solving-offline-2.27.0-linux-x86_64-py312-runtime.tar.gz`
  - `dist/planner-solving-offline-2.27.0-linux-x86_64-py312-runtime.tar.gz.sha256`
  - `dist/install-planner-solving.sh`
  - `dist/README-INSTALL.txt`
