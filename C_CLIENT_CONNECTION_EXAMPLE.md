# C-Client 连接 B-Client WebSocket 示例

## 概述

C-Client 需要通过动态发现机制连接到 B-Client 的 WebSocket 服务器。由于 B-Client 在 ASGI 部署中使用动态端口（HTTP端口+1），C-Client 不能硬编码端口号。

## 连接流程

### 1. 发现 WebSocket 信息

C-Client 首先调用 B-Client 的端口发现 API：

```javascript
// 方法1: 获取简化信息
async function discoverWebSocketInfo(baseUrl) {
    try {
        const response = await fetch(`${baseUrl}/api/b-client/websocket-info`);
        const info = await response.json();
        
        return {
            websocketUrl: info.websocket_url,
            websocketPort: info.websocket_port,
            httpPort: info.http_port,
            environment: info.environment
        };
    } catch (error) {
        console.error('Failed to discover WebSocket info:', error);
        throw error;
    }
}

// 方法2: 获取详细配置信息
async function getBClientInfo(baseUrl) {
    try {
        const response = await fetch(`${baseUrl}/api/b-client/info`);
        const data = await response.json();
        
        if (data.success) {
            return data.b_client_info;
        } else {
            throw new Error(data.error);
        }
    } catch (error) {
        console.error('Failed to get B-Client info:', error);
        throw error;
    }
}
```

### 2. 建立 WebSocket 连接

```javascript
async function connectToBClient(baseUrl) {
    try {
        // 1. 发现 WebSocket 信息
        const wsInfo = await discoverWebSocketInfo(baseUrl);
        console.log('WebSocket info:', wsInfo);
        
        // 2. 构建 WebSocket URL
        // 注意: 在生产环境中，需要使用实际的域名/IP
        const wsUrl = `ws://${baseUrl.replace('http://', '').replace('https://', '')}:${wsInfo.websocketPort}`;
        console.log('Connecting to WebSocket:', wsUrl);
        
        // 3. 建立 WebSocket 连接
        const ws = new WebSocket(wsUrl);
        
        ws.onopen = function(event) {
            console.log('WebSocket connected');
            
            // 4. 发送注册消息
            const registrationMessage = {
                type: 'c_client_register',
                client_id: `c-client-${Date.now()}`,
                user_id: 'your-user-id',
                username: 'your-username',
                node_id: 'your-node-id',
                domain_id: 'your-domain-id',
                cluster_id: 'your-cluster-id',
                channel_id: 'your-channel-id'
            };
            
            ws.send(JSON.stringify(registrationMessage));
        };
        
        ws.onmessage = function(event) {
            const message = JSON.parse(event.data);
            console.log('Received message:', message);
            
            // 处理不同类型的消息
            switch (message.type) {
                case 'auto_login':
                    handleAutoLogin(message);
                    break;
                case 'logout_notification':
                    handleLogoutNotification(message);
                    break;
                case 'session_feedback':
                    handleSessionFeedback(message);
                    break;
                default:
                    console.log('Unknown message type:', message.type);
            }
        };
        
        ws.onclose = function(event) {
            console.log('WebSocket disconnected:', event.code, event.reason);
        };
        
        ws.onerror = function(error) {
            console.error('WebSocket error:', error);
        };
        
        return ws;
        
    } catch (error) {
        console.error('Failed to connect to B-Client:', error);
        throw error;
    }
}
```

### 3. Python 示例

```python
import asyncio
import websockets
import requests
import json

async def discover_and_connect(base_url):
    """发现 WebSocket 信息并建立连接"""
    try:
        # 1. 发现 WebSocket 信息
        response = requests.get(f"{base_url}/api/b-client/websocket-info")
        ws_info = response.json()
        
        print(f"WebSocket info: {ws_info}")
        
        # 2. 构建 WebSocket URL
        ws_host = ws_info['websocket_host']
        ws_port = ws_info['websocket_port']
        ws_url = f"ws://{ws_host}:{ws_port}"
        
        print(f"Connecting to WebSocket: {ws_url}")
        
        # 3. 建立 WebSocket 连接
        async with websockets.connect(ws_url) as websocket:
            print("WebSocket connected")
            
            # 4. 发送注册消息
            registration_message = {
                "type": "c_client_register",
                "client_id": f"c-client-{int(asyncio.get_event_loop().time())}",
                "user_id": "your-user-id",
                "username": "your-username",
                "node_id": "your-node-id",
                "domain_id": "your-domain-id",
                "cluster_id": "your-cluster-id",
                "channel_id": "your-channel-id"
            }
            
            await websocket.send(json.dumps(registration_message))
            print("Registration message sent")
            
            # 5. 监听消息
            async for message in websocket:
                data = json.loads(message)
                print(f"Received message: {data}")
                
                # 处理不同类型的消息
                if data.get('type') == 'auto_login':
                    await handle_auto_login(data)
                elif data.get('type') == 'logout_notification':
                    await handle_logout_notification(data)
                elif data.get('type') == 'session_feedback':
                    await handle_session_feedback(data)
                
    except Exception as e:
        print(f"Connection failed: {e}")

async def handle_auto_login(data):
    """处理自动登录消息"""
    print("Handling auto login:", data)
    # 实现自动登录逻辑

async def handle_logout_notification(data):
    """处理登出通知"""
    print("Handling logout notification:", data)
    # 实现登出逻辑

async def handle_session_feedback(data):
    """处理会话反馈"""
    print("Handling session feedback:", data)
    # 实现会话反馈处理

# 使用示例
if __name__ == "__main__":
    base_url = "http://your-b-client-domain.com"  # 或本地 "http://localhost:8000"
    asyncio.run(discover_and_connect(base_url))
```

## 端口计算逻辑

### 本地开发环境
- HTTP端口: 8000 (或配置的端口)
- WebSocket端口: 8766 (固定端口)

### 生产环境 (Heroku)
- HTTP端口: `$PORT` (Heroku自动分配，如 12345)
- WebSocket端口: `$PORT + 1` (如 12346)

## 错误处理

```javascript
async function connectWithRetry(baseUrl, maxRetries = 3) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            console.log(`Connection attempt ${attempt}/${maxRetries}`);
            return await connectToBClient(baseUrl);
        } catch (error) {
            console.error(`Attempt ${attempt} failed:`, error);
            
            if (attempt === maxRetries) {
                throw new Error(`Failed to connect after ${maxRetries} attempts: ${error.message}`);
            }
            
            // 等待后重试
            await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        }
    }
}
```

## 安全考虑

1. **域名验证**: 在生产环境中，确保使用正确的域名
2. **HTTPS/WSS**: 在生产环境中使用安全连接
3. **认证**: 在WebSocket连接中实现适当的认证机制

## 测试连接

```bash
# 测试端口发现API
curl http://localhost:8000/api/b-client/websocket-info

# 测试详细配置API
curl http://localhost:8000/api/b-client/info

# 测试WebSocket连接 (使用wscat)
wscat -c ws://localhost:8766
```

## 注意事项

1. **动态端口**: 永远不要硬编码WebSocket端口号
2. **环境差异**: 本地开发和生产环境的端口计算逻辑不同
3. **连接重试**: 实现适当的重试机制
4. **错误处理**: 妥善处理连接失败的情况
5. **消息格式**: 确保发送的消息格式符合B-Client的期望
