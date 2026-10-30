# AI Target — Мультиагентная система автозапуска рекламы и сквозной аналитики

6-ролевая мультиагентная система управления таргетированной рекламой (Instagram/Meta Ads, TikTok Ads, Telegram Ads через TON/Adsly.Pro, Telegram Mini Apps через AdsGram/RichAds, посевы в Telega.in и Google Ads AI Max) со сквозной CRM-воронкой и ИИ-копилотом для маркетолога.

## Возможности
- **Supervisor Agent (`supervisor.py`)**: Сбор брифа (продукт, ГЕО, цель, бюджет), оркестрация через единый контракт `CampaignState`, жесткий гейткипинг оплаты (`PaymentGatekeeper`, запуск только при `payment_verified: true`) и управление рекомендациями (`PENDING_USER_DECISION` -> `APPROVED` / `REJECTED`).
- **Strategist & Billing Agent (`strategist.py`)**: Автоматическое удержание сервисной комиссии (12%), учет агентского кешбэка (3–6% Click.ru / eLama) и распределение бюджета по порогам входа площадок.
- **Creative Copywriter Agent (`copywriter.py`)**: Генерация A/B-вариантов креативов под жесткие правила модерации площадок (Telegram Ads <= 160 символов без внешних ссылок, хуки для Reels, пуш-баннеры для RichAds, нативные посты для Telega.in) и автоматическая UTM-разметка.
- **Technical Executors (`meta_tiktok.py`, `telegram_ecosystem.py`)**: Сборка и отправка цепочки `Campaign -> AdSet -> Ad` в статусе `PAUSED` / `DISABLE`, парсинг каналов конкурентов и выставление ставок в TON (>= 0.1 TON).
- **Analytics & Guardrails Agent (`analytics.py`)**:
  - Мониторинг каждые 2 часа, проверка фазы обучения Meta Ads (50 конверсий).
  - **Kill-Switch**: автоматическая остановка кампаний и отдельных Reels при перерасходе >= 1.5x от целевого CPA без конверсий.
  - **Поштучная диагностика каждого Reels**: объяснение причин низкой конверсии (слабый хук первых 3 секунд, низкий CTR, просад на посадке или в отделе продаж) и формирование рекомендаций для маркетолога.
  - **Сквозная CRM-воронка**: учет показов, кликов, сколько человек написали (`messages_received`) и сколько реально купили (`sales_count`), расчет `cost_per_message`, `cost_per_sale` (CAC) и `ROAS`.

## Быстрый старт

```powershell
# Запуск демо-симуляции
$env:PYTHONPATH="src"
python -m ai_target

# Запуск с пользовательскими параметрами
python -m ai_target --product "Доставка с Poizon за 7 дней" --geo "UZ,KZ" --goal "bot_activations" --budget 500

# Запуск 4-уровневого набора E2E-тестов (89 тестов)
python run_tests.py

# Запуск полного набора Unit + E2E тестов (456 тестов)
pytest -v
```
