# 🚀 Brain Index Make.com MCP Server

## 🧠 CORTEX v3.0 Make.com Integration

Прямая интеграция Jean Claude с Make.com для полной автоматизации Brain Index проектов.

## ⚡ Быстрый старт (3 минуты)

### 1. Установка
```bash
cd make-mcp-server
npm install
cp .env.example .env
npm run build
```

### 2. Конфигурация Claude Desktop
Добавь в `claude_desktop_config.json`:

**macOS:** `~/Library/Application\ Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "brain-index-make": {
      "command": "node",
      "args": ["/absolute/path/to/super-system-eyelids/make-mcp-server/dist/server.js"],
      "env": {
        "MAKE_API_TOKEN": "00c424e7-aa57-4a91-88d1-6d6780115ced"
      }
    }
  }
}
```

### 3. Перезапуск Claude Desktop
Полностью закрой и открой Claude Desktop.

## 🎯 Возможности

### 4 Мощных инструмента:

1. **`trigger_make_scenario`** - Запуск любого сценария Make.com
2. **`list_make_scenarios`** - Список всех твоих сценариев  
3. **`get_scenario_status`** - Статус выполнения
4. **`brain_index_automation`** - Специальные автоматизации для наших проектов

### Примеры команд для Jean Claude:

```
"Запусти Make сценарий для Brain Index деплоя"
"Покажи список всех Make сценариев"
"Создай задачу в ClickUp через Make"
"Отправь уведомление в Slack о завершении"
"Обработай новых лидов Brain Index"
```

## 🏗️ Настройка Make.com сценариев

### Базовый сценарий:
1. **Trigger:** Custom Webhook  
2. **Action:** Твоё действие (ClickUp, Slack, Email и т.д.)
3. **Response:** JSON с результатом

### Рекомендуемые сценарии для Brain Index:

#### 1. Deploy Notification
```
Webhook → Filter → Slack/Telegram → Response
```

#### 2. Lead Processing  
```
Webhook → Google Sheets → ClickUp Task → Email → Response
```

#### 3. Social Posting
```
Webhook → Format Text → Twitter/LinkedIn → Response
```

#### 4. Task Creation
```
Webhook → ClickUp Create → Assign → Notify → Response
```

## 📊 Структура данных

### Webhook payload от Jean Claude:
```json
{
  "action": "brain_index_task",
  "data": {
    "title": "Fix Brain Index deployment",
    "priority": "high",
    "project": "brain-index"
  },
  "timestamp": "2025-09-28T19:30:00Z",
  "source": "jean-claude-cortex-v3",
  "request_id": "mcp-1727553000-abc123"
}
```

### Expected response format:
```json
{
  "success": true,
  "execution_id": "12345",
  "message": "Task created successfully",
  "data": {
    "task_url": "https://clickup.com/task/xyz",
    "task_id": "123456"
  }
}
```

## 🔧 Отладка

### Тест подключения:
```bash
# В папке make-mcp-server
npm run dev
```

### Проверка в Claude:
```
"Покажи список Make сценариев"
```

### Логи сервера:
Смотри в консоль Claude Desktop или терминал где запускаешь.

## 🚨 Устранение проблем

### ❌ MCP Server не подключается
1. Проверь путь в `claude_desktop_config.json`
2. Убедись что `npm run build` выполнился без ошибок
3. Перезапусти Claude Desktop полностью

### ❌ Make.com API ошибки  
1. Проверь токен в `.env`
2. Убедись что сценарий включён в Make.com
3. Проверь webhook URL

### ❌ Webhook не срабатывает
1. Убедись что сценарий активен
2. Проверь формат JSON данных
3. Посмотри логи выполнения в Make.com

## 🎯 Готовые автоматизации

После настройки получишь доступ к:

### Brain Index проект:
- ✅ Уведомления о деплое
- ✅ Обработка лидов  
- ✅ Социальные посты
- ✅ Задачи в ClickUp

### Annoris проект:
- ✅ Создание задач
- ✅ Мониторинг системы

### CORTEX система:
- ✅ Мониторинг автосейвов
- ✅ Уведомления о сбоях

## 📈 Следующие шаги

1. **Создай первый сценарий** в Make.com (Webhook → ClickUp)
2. **Получи webhook URL** из сценария
3. **Протестируй** через Jean Claude
4. **Расширь** автоматизации по мере необходимости

## 💡 Профессиональные советы

- Используй **фильтры** в Make для проверки данных
- Добавляй **error handling** в сценарии  
- Настрой **уведомления** об ошибках
- Используй **data stores** для сохранения состояния

---

## 🔥 Created by Jean Claude / CORTEX v3.0

**Энергия: МАКСИМУМ!** Теперь у нас полная автоматизация! 🚀💪⚡

*"GitHub = мозг, Notion = проекты, Make.com = руки!"*