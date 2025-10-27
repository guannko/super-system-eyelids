#!/bin/bash

echo "🚀 Setting up n8n MCP Server..."

# Install n8n MCP server globally
echo "📦 Installing @modelcontextprotocol/server-n8n..."
npm install -g @modelcontextprotocol/server-n8n

# Create MCP configuration directory
mkdir -p ~/.config/mcp

# Copy configuration
echo "⚙️  Copying MCP configuration..."
cp n8n-mcp-config.json ~/.config/mcp/

echo "✅ n8n MCP setup complete!"
echo ""
echo "📋 Configuration location: ~/.config/mcp/n8n-mcp-config.json"
echo "🔧 Test connection with: npx @modelcontextprotocol/server-n8n --apiUrl https://annoris.app.n8n.cloud --apiKey YOUR_API_KEY"
echo ""
echo "🎯 To use with Claude Desktop, add this to your config:"
echo ""
cat n8n-mcp-config.json