# B-Client ASGI 部署指南

## 概述

本项目已配置支持 ASGI 部署，使用 Hypercorn 作为 ASGI 服务器。这允许在同一进程中同时运行 Flask HTTP 路由和 WebSocket 服务器。

## 架构说明

### 当前架构
- **HTTP 服务器**: Flask 应用 (通过 WSGI-to-ASGI 适配器)
- **WebSocket 服务器**: CClientWebSocketClient 类 (运行在独立端口)
- **ASGI 服务器**: Hypercorn

### 端口配置
- **HTTP 端口**: `$PORT` (Heroku 自动分配)
- **WebSocket 端口**: `$PORT + 1` (HTTP 端口 + 1)

### 端口发现机制

B端通过以下API端点向C-Client暴露WebSocket连接信息：

1. **详细配置信息**: `GET /api/b-client/info`
   ```json
   {
     "success": true,
     "b_client_info": {
       "websocket": {
         "enabled": true,
         "host": "0.0.0.0",
         "port": 8001,
         "environment": "production"
       },
       "api_port": 8000,
       "websocket_port": 8001,
       "hostname": "your-app-name",
       "local_ip": "10.x.x.x"
     }
   }
   ```

2. **简化WebSocket信息**: `GET /api/b-client/websocket-info`
   ```json
   {
     "websocket_url": "ws://0.0.0.0:8001",
     "websocket_host": "0.0.0.0",
     "websocket_port": 8001,
     "http_port": 8000,
     "environment": "production"
   }
   ```

C-Client应该首先调用这些API获取WebSocket连接信息，而不是硬编码端口号。

## 部署配置

### 1. Procfile 配置

当前 Procfile 配置为：
```
web: hypercorn asgi_app:asgi_app --bind 0.0.0.0:$PORT
```

### 2. 依赖项

已添加以下依赖到 `requirements.txt`：
```
hypercorn==0.17.2
asgiref==3.8.1
```

### 3. 文件结构

- `asgi_app.py` - ASGI 应用入口
- `wsgi_app.py` - WSGI 应用备选方案
- `test_asgi.py` - 配置测试脚本

## 使用方法

### 本地测试

1. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

2. **运行测试**:
   ```bash
   python test_asgi.py
   ```

3. **启动 ASGI 服务器**:
   ```bash
   python asgi_app.py
   ```

4. **或使用 Hypercorn 直接启动**:
   ```bash
   hypercorn asgi_app:asgi_app --bind 0.0.0.0:8000
   ```

### Heroku 部署

1. **推送代码**:
   ```bash
   git add .
   git commit -m "Add ASGI support with Hypercorn"
   git push heroku main
   ```

2. **查看日志**:
   ```bash
   heroku logs --tail
   ```

## 配置选项

### 环境变量

- `PORT` - Heroku 自动设置，用于 HTTP 服务器
- `HOST` - 服务器绑定地址 (默认: 0.0.0.0)
- `DEBUG` - 调试模式 (默认: False)

### WebSocket 配置

WebSocket 服务器使用以下配置：
- **主机**: 0.0.0.0
- **端口**: $PORT + 1
- **处理器**: `CClientWebSocketClient.handle_c_client_connection`

## 故障排除

### 常见问题

1. **WebSocket 服务器启动失败**
   - 检查端口是否被占用
   - 查看日志中的错误信息

2. **ASGI 应用导入失败**
   - 确保所有依赖已安装
   - 运行 `python test_asgi.py` 检查配置

3. **HTTP 路由不工作**
   - 检查 asgiref 是否正确安装
   - 验证 Flask 应用配置

### 日志检查

查看详细的启动日志：
```bash
# 本地
python asgi_app.py

# Heroku
heroku logs --tail
```

## 备选方案

### WSGI 部署

如果 ASGI 部署有问题，可以使用 WSGI 方案：

1. **修改 Procfile**:
   ```
   web: gunicorn wsgi_app:wsgi_app --bind 0.0.0.0:$PORT --workers 1
   ```

2. **添加 Gunicorn 依赖**:
   ```
   gunicorn==21.2.0
   ```

### 原始 Flask 部署

回到原始部署方式：
```
web: python run.py
```

## 性能优化

### 生产环境建议

1. **使用多进程**:
   ```bash
   hypercorn asgi_app:asgi_app --bind 0.0.0.0:$PORT --workers 4
   ```

2. **调整 WebSocket 配置**:
   - 增加 ping 间隔
   - 调整消息队列大小

3. **监控资源使用**:
   - 内存使用情况
   - WebSocket 连接数
   - HTTP 请求响应时间

## 安全考虑

1. **CORS 配置**: 确保正确的跨域设置
2. **WebSocket 安全**: 验证连接来源
3. **端口访问**: 限制 WebSocket 端口的外部访问

## 监控和维护

1. **健康检查**: 使用 `/api/health` 端点
2. **WebSocket 状态**: 使用 `/api/c-client/status` 端点
3. **日志监控**: 定期检查应用日志

## 联系支持

如果遇到部署问题，请检查：
1. 运行 `python test_asgi.py` 的结果
2. Heroku 日志输出
3. 端口配置是否正确
