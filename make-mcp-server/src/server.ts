#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import axios from 'axios';
import dotenv from 'dotenv';

dotenv.config();

class BrainIndexMakeMCPServer {
  private server: Server;
  private makeApiToken: string;
  private makeBaseUrl: string;

  constructor() {
    this.makeApiToken = process.env.MAKE_API_TOKEN || '00c424e7-aa57-4a91-88d1-6d6780115ced';
    this.makeBaseUrl = 'https://eu1.make.com/api/v2';
    
    this.server = new Server(
      {
        name: 'brain-index-make-server',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
    this.logStartup();
  }

  private logStartup() {
    console.error('🚀 Brain Index Make MCP Server starting...');
    console.error(`🔑 API Token: ${this.makeApiToken ? '✅ Configured' : '❌ Missing'}`);
    console.error(`🌐 Base URL: ${this.makeBaseUrl}`);
  }

  private setupToolHandlers() {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      return {
        tools: [
          {
            name: 'trigger_make_scenario',
            description: '🚀 Запустить Make.com сценарий с данными',
            inputSchema: {
              type: 'object',
              properties: {
                webhook_url: {
                  type: 'string',
                  description: 'URL webhook\'а сценария Make.com'
                },
                action: {
                  type: 'string',
                  description: 'Тип действия',
                  enum: ['brain_index_task', 'deploy_notification', 'lead_processing', 'social_post', 'custom']
                },
                data: {
                  type: 'object',
                  description: 'Данные для передачи в сценарий',
                  additionalProperties: true
                }
              },
              required: ['webhook_url', 'action']
            }
          },
          {
            name: 'list_make_scenarios',
            description: '📋 Получить список всех сценариев Make.com',
            inputSchema: {
              type: 'object',
              properties: {
                filter: {
                  type: 'string',
                  description: 'Фильтр для поиска сценариев'
                }
              }
            }
          },
          {
            name: 'get_scenario_status',
            description: '📊 Проверить статус выполнения сценария',
            inputSchema: {
              type: 'object',
              properties: {
                scenario_id: {
                  type: 'string',
                  description: 'ID сценария'
                }
              },
              required: ['scenario_id']
            }
          },
          {
            name: 'brain_index_automation',
            description: '🧠 Специальные автоматизации для Brain Index',
            inputSchema: {
              type: 'object',
              properties: {
                automation_type: {
                  type: 'string',
                  description: 'Тип автоматизации',
                  enum: ['deploy_notification', 'lead_capture', 'social_posting', 'task_creation', 'monitoring']
                },
                project: {
                  type: 'string',
                  description: 'Проект (brain-index, annoris, offerspsp)',
                  enum: ['brain-index', 'annoris', 'offerspsp', 'cortex']
                },
                data: {
                  type: 'object',
                  description: 'Данные автоматизации'
                }
              },
              required: ['automation_type', 'project']
            }
          }
        ]
      };
    });

    // Handle tool calls
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          case 'trigger_make_scenario':
            return await this.triggerMakeScenario(args);
          case 'list_make_scenarios':
            return await this.listMakeScenarios(args);
          case 'get_scenario_status':
            return await this.getScenarioStatus(args);
          case 'brain_index_automation':
            return await this.brainIndexAutomation(args);
          default:
            throw new McpError(ErrorCode.MethodNotFound, `❌ Неизвестный инструмент: ${name}`);
        }
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Неизвестная ошибка';
        console.error(`❌ Tool execution failed: ${errorMessage}`);
        throw new McpError(ErrorCode.InternalError, `Ошибка выполнения: ${errorMessage}`);
      }
    });
  }

  private async triggerMakeScenario(args: any) {
    if (!args.webhook_url) {
      throw new Error('Не указан webhook_url');
    }

    const payload = {
      action: args.action,
      data: args.data || {},
      timestamp: new Date().toISOString(),
      source: 'jean-claude-cortex-v3',
      request_id: `mcp-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      project: 'brain-index'
    };

    try {
      const response = await axios.post(args.webhook_url, payload, {
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Brain-Index-MCP-Server/1.0.0',
          'X-Source': 'jean-claude'
        },
        timeout: 30000
      });

      return {
        content: [
          {
            type: 'text',
            text: `✅ Make.com сценарий запущен!
            
🎯 Действие: ${args.action}
📡 Статус: ${response.status}
🆔 Request ID: ${payload.request_id}
⏰ Время: ${payload.timestamp}
📊 Данные переданы: ${Object.keys(args.data || {}).length} полей

🔗 Webhook: ${args.webhook_url.substring(0, 50)}...`
          }
        ]
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || 'N/A';
        const statusText = error.response?.statusText || 'Unknown';
        
        throw new Error(
          `❌ HTTP ошибка: ${status} - ${statusText}\n` +
          `🔗 URL: ${args.webhook_url}\n` +
          `💡 Проверь статус сценария в Make.com`
        );
      }
      throw error;
    }
  }

  private async listMakeScenarios(args: any) {
    try {
      const response = await axios.get(`${this.makeBaseUrl}/scenarios`, {
        headers: {
          'Authorization': `Token ${this.makeApiToken}`,
          'Content-Type': 'application/json'
        },
        params: {
          limit: 20,
          offset: 0
        }
      });

      const scenarios = response.data.scenarios || [];
      const filteredScenarios = args.filter 
        ? scenarios.filter((s: any) => s.name.toLowerCase().includes(args.filter.toLowerCase()))
        : scenarios;

      let scenarioList = filteredScenarios.map((scenario: any) => 
        `📋 ${scenario.name} (ID: ${scenario.id})\n` +
        `   📊 Статус: ${scenario.is_running ? '🟢 Активен' : '🔴 Остановлен'}\n` +
        `   🔗 Webhook: ${scenario.webhook_url || 'Не настроен'}`
      ).join('\n\n');

      if (scenarioList === '') {
        scenarioList = '📭 Сценарии не найдены';
      }

      return {
        content: [
          {
            type: 'text',
            text: `📋 Make.com Сценарии (${filteredScenarios.length}/${scenarios.length}):

${scenarioList}

💡 Используй trigger_make_scenario с webhook_url для запуска`
          }
        ]
      };
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        throw new Error('❌ Неверный API токен Make.com');
      }
      throw new Error(`❌ Ошибка получения сценариев: ${error}`);
    }
  }

  private async getScenarioStatus(args: any) {
    try {
      const response = await axios.get(`${this.makeBaseUrl}/scenarios/${args.scenario_id}`, {
        headers: {
          'Authorization': `Token ${this.makeApiToken}`,
          'Content-Type': 'application/json'
        }
      });

      const scenario = response.data;
      
      return {
        content: [
          {
            type: 'text',
            text: `📊 Статус сценария: ${scenario.name}

🆔 ID: ${scenario.id}
📊 Статус: ${scenario.is_running ? '🟢 Запущен' : '🔴 Остановлен'}
📅 Создан: ${new Date(scenario.created_at).toLocaleDateString()}
📈 Последнее выполнение: ${scenario.last_run ? new Date(scenario.last_run).toLocaleString() : 'Не запускался'}
🔗 Webhook: ${scenario.webhook_url || 'Не настроен'}`
          }
        ]
      };
    } catch (error) {
      throw new Error(`❌ Ошибка получения статуса: ${error}`);
    }
  }

  private async brainIndexAutomation(args: any) {
    // Pre-configured webhooks for Brain Index projects
    const BRAIN_INDEX_WEBHOOKS = {
      'brain-index': {
        deploy_notification: 'https://hook.eu1.make.com/your-brain-index-deploy-webhook',
        lead_capture: 'https://hook.eu1.make.com/your-brain-index-leads-webhook',
        social_posting: 'https://hook.eu1.make.com/your-brain-index-social-webhook'
      },
      'annoris': {
        task_creation: 'https://hook.eu1.make.com/your-annoris-tasks-webhook',
        monitoring: 'https://hook.eu1.make.com/your-annoris-monitoring-webhook'
      },
      'cortex': {
        monitoring: 'https://hook.eu1.make.com/your-cortex-monitoring-webhook'
      }
    };

    const webhooks = BRAIN_INDEX_WEBHOOKS[args.project as keyof typeof BRAIN_INDEX_WEBHOOKS];
    const webhook_url = webhooks?.[args.automation_type as keyof typeof webhooks];

    if (!webhook_url) {
      return {
        content: [
          {
            type: 'text',
            text: `⚠️ Автоматизация не настроена
            
🎯 Проект: ${args.project}
🔧 Тип: ${args.automation_type}

💡 Нужно создать webhook в Make.com и обновить конфигурацию в коде.

📋 Доступные автоматизации:
${Object.entries(BRAIN_INDEX_WEBHOOKS).map(([proj, automations]) => 
  `• ${proj}: ${Object.keys(automations).join(', ')}`
).join('\n')}`
          }
        ]
      };
    }

    // Trigger the automation with special Brain Index payload
    return await this.triggerMakeScenario({
      webhook_url,
      action: `${args.project}_${args.automation_type}`,
      data: {
        ...args.data,
        project: args.project,
        automation_type: args.automation_type,
        triggered_by: 'jean-claude',
        cortex_version: 'v3.0'
      }
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('🚀 Brain Index Make MCP Server запущен!');
    console.error('🔥 Жан Клод готов к автоматизации! ПОЕХАЛИ! 💪⚡');
  }
}

const server = new BrainIndexMakeMCPServer();
server.run().catch((error) => {
  console.error('❌ MCP Server failed to start:', error);
  process.exit(1);
});