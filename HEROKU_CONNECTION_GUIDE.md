# Heroku B-Client 连接配置指南

## 当前问题分析

根据您的代码分析，发现以下需要修改的地方：

### 1. NSN 配置问题
- **当前配置**: NSN硬编码了B-Client的WebSocket端口为8766
- **问题**: Heroku部署后，B-Client使用动态端口（HTTP端口+1）
- **解决方案**: 修改NSN配置，使其动态获取B-Client的WebSocket端口

### 2. C-Client 连接问题
- **当前配置**: C-Client从NSN获取固定的WebSocket URL
- **问题**: 无法适应Heroku的动态端口
- **解决方案**: 实现动态端口发现机制

## 修改方案

### 方案一：修改NSN配置（推荐）

#### 1. 修改NSN的config.env文件

```bash
# 本地开发环境
NSN_ENVIRONMENT=local
B_CLIENT_API_URL=http://localhost:3000
B_CLIENT_WEBSOCKET_URL=ws://127.0.0.1:8766
NSN_URL=http://localhost:5000

# 生产环境 - 使用动态发现
NSN_ENVIRONMENT=production
B_CLIENT_API_URL=https://your-b-client-app.herokuapp.com
B_CLIENT_WEBSOCKET_URL=dynamic  # 标记为动态获取
NSN_URL=https://comp693nsnproject.pythonanywhere.com
```

#### 2. 修改NSN的config.py

```python
import os

# NSN Environment Configuration
NSN_ENVIRONMENT = os.getenv('NSN_ENVIRONMENT', 'local')

# B-Client API URL
B_CLIENT_API_URL = os.getenv('B_CLIENT_API_URL', 'http://localhost:3000')
B_CLIENT_WEBSOCKET_URL = os.getenv('B_CLIENT_WEBSOCKET_URL', 'ws://127.0.0.1:8766')

# 动态WebSocket URL获取
def get_b_client_websocket_url():
    """动态获取B-Client WebSocket URL"""
    if B_CLIENT_WEBSOCKET_URL == 'dynamic':
        try:
            import requests
            # 调用B-Client的端口发现API
            response = requests.get(f"{B_CLIENT_API_URL}/api/b-client/websocket-info", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('websocket_url', f"ws://{B_CLIENT_API_URL.replace('http://', '').replace('https://', '')}:{data.get('websocket_port', 8766)}")
        except Exception as e:
            print(f"Failed to get dynamic WebSocket URL: {e}")
    
    return B_CLIENT_WEBSOCKET_URL

# 动态获取WebSocket URL
B_CLIENT_WEBSOCKET_URL_DYNAMIC = get_b_client_websocket_url()
```

#### 3. 修改NSN的login.py

```python
# 在inject_nmp_and_websocket_vars函数中
def inject_nmp_and_websocket_vars():
    """Inject NMP parameters and WebSocket connection variables into all templates"""
    # ... 现有代码 ...
    
    # 动态获取WebSocket URL
    websocket_url = get_b_client_websocket_url()
    
    # ... 其余代码使用websocket_url ...
```

### 方案二：修改C-Client配置

#### 1. 修改C-Client的bClientConfigManager.js

```javascript
class BClientConfigManager {
    constructor() {
        this.configPath = path.join(__dirname, '..', 'config.json');
        this.config = this.loadConfig();
    }

    // 添加动态WebSocket URL获取方法
    async getDynamicWebSocketUrl(baseUrl) {
        try {
            const response = await fetch(`${baseUrl}/api/b-client/websocket-info`);
            const data = await response.json();
            return data.websocket_url;
        } catch (error) {
            console.error('Failed to get dynamic WebSocket URL:', error);
            return null;
        }
    }

    // 修改getWebSocketConfig方法
    async getWebSocketConfig() {
        const currentEnv = this.getCurrentEnvironment();
        const envConfig = this.getEnvironmentConfig(currentEnv);
        const wsConfig = this.config.b_client_websocket || {};

        // 如果是生产环境，尝试动态获取WebSocket URL
        if (currentEnv === 'production' && envConfig?.dynamic_websocket) {
            try {
                const dynamicUrl = await this.getDynamicWebSocketUrl(envConfig.base_url);
                if (dynamicUrl) {
                    const url = new URL(dynamicUrl);
                    return {
                        enabled: wsConfig.enabled !== false,
                        host: url.hostname,
                        port: parseInt(url.port),
                        auto_reconnect: wsConfig.auto_reconnect !== false,
                        reconnect_interval: wsConfig.reconnect_interval || 30,
                        environment: currentEnv,
                        environment_name: envConfig?.name || `${currentEnv} B-Client`
                    };
                }
            } catch (error) {
                console.error('Dynamic WebSocket URL fetch failed:', error);
            }
        }

        // 回退到静态配置
        return {
            enabled: wsConfig.enabled !== false,
            host: envConfig?.host || 'localhost',
            port: envConfig?.port || 8766,
            auto_reconnect: wsConfig.auto_reconnect !== false,
            reconnect_interval: wsConfig.reconnect_interval || 30,
            environment: currentEnv,
            environment_name: envConfig?.name || `${currentEnv} B-Client`
        };
    }
}
```

#### 2. 修改C-Client的config.json

```json
{
  "b_client_websocket": {
    "enabled": true,
    "auto_reconnect": false,
    "reconnect_interval": 60
  },
  "b_client_environment": {
    "current": "production",
    "local": {
      "name": "Local B-Client",
      "host": "localhost",
      "port": 8766,
      "description": "Connect to local B-Client for development"
    },
    "production": {
      "name": "Production B-Client",
      "base_url": "https://your-b-client-app.herokuapp.com",
      "dynamic_websocket": true,
      "description": "Connect to production B-Client server with dynamic port discovery"
    }
  },
  "nmp_cooperative_website": {
    "current": "production",
    "local": {
      "name": "Local NSN",
      "host": "localhost",
      "port": 5000,
      "url": "http://localhost:5000",
      "description": "Local development NSN website"
    },
    "production": {
      "name": "Production NSN",
      "host": "comp693nsnproject.pythonanywhere.com",
      "port": 443,
      "url": "https://comp693nsnproject.pythonanywhere.com",
      "description": "Production NSN website"
    }
  }
}
```

### 方案三：直接在C-Client中实现动态发现

#### 修改C-Client的连接管理器

```javascript
// 在connectionManager.js中添加动态发现方法
async connectToBClientWithDiscovery(baseUrl) {
    try {
        // 1. 获取WebSocket信息
        const response = await fetch(`${baseUrl}/api/b-client/websocket-info`);
        const wsInfo = await response.json();
        
        if (wsInfo.websocket_url) {
            // 2. 使用发现的WebSocket URL连接
            return await this.connectToWebSocketUrl(wsInfo.websocket_url, 'B-Client (Dynamic)');
        } else {
            throw new Error('No WebSocket URL found in response');
        }
    } catch (error) {
        this.logger.error('Dynamic B-Client discovery failed:', error);
        return false;
    }
}
```

## 部署步骤

### 1. 更新B-Client部署

确保您的B-Client已经部署到Heroku并包含：
- ✅ `asgi_app.py` - ASGI应用
- ✅ `Procfile` - Hypercorn配置
- ✅ `requirements.txt` - 包含hypercorn和asgiref
- ✅ 端口发现API端点

### 2. 更新NSN配置

```bash
# 在NSN的config.env中设置
NSN_ENVIRONMENT=production
B_CLIENT_API_URL=https://your-b-client-app.herokuapp.com
B_CLIENT_WEBSOCKET_URL=dynamic
NSN_URL=https://comp693nsnproject.pythonanywhere.com
```

### 3. 更新C-Client配置

```bash
# 在C-Client的config.json中设置
"current": "production"
```

## 测试连接

### 1. 测试B-Client端口发现API

```bash
# 测试端口发现
curl https://your-b-client-app.herokuapp.com/api/b-client/websocket-info

# 预期响应
{
  "websocket_url": "ws://0.0.0.0:12346",
  "websocket_host": "0.0.0.0",
  "websocket_port": 12346,
  "http_port": 12345,
  "environment": "production"
}
```

### 2. 测试NSN配置

```bash
# 测试NSN环境变量API
curl https://comp693nsnproject.pythonanywhere.com/api/nsn_websocket_env

# 预期响应应包含正确的B-Client URL
```

### 3. 测试C-Client连接

启动C-Client并检查日志，确认：
- ✅ 成功获取WebSocket信息
- ✅ 成功连接到B-Client
- ✅ 成功注册用户

## 故障排除

### 常见问题

1. **端口发现失败**
   - 检查B-Client是否正常运行
   - 验证API端点是否可访问
   - 检查CORS设置

2. **WebSocket连接失败**
   - 确认WebSocket端口是否正确
   - 检查防火墙设置
   - 验证WebSocket服务器是否启动

3. **环境配置错误**
   - 确认所有环境变量设置正确
   - 检查配置文件格式
   - 验证URL格式

## 总结

推荐使用**方案一**（修改NSN配置），因为：
- ✅ 集中管理B-Client连接信息
- ✅ C-Client无需修改
- ✅ 更容易维护和更新
- ✅ 符合现有的架构设计

这样，当B-Client部署到Heroku后，NSN会自动发现正确的WebSocket端口，C-Client就能正常连接了。
