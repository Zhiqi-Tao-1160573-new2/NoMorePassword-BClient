# WebSocket Server Startup Fix

## 问题描述
B-Client的WebSocket服务器没有在Heroku上启动，导致C-Client无法连接。

## 解决方案
修改了`asgi_app.py`，让WebSocket服务器在第一个HTTP请求时启动，而不是在模块导入时启动。

## 需要手动部署的更改

### 1. 推送代码到GitHub
由于权限问题，需要手动推送代码：

```bash
git push origin main
```

### 2. 部署到Heroku
推送成功后，Heroku会自动部署。或者手动触发：

```bash
git push heroku main
```

## 预期效果
部署后，当有HTTP请求到达时，应该看到以下日志：

```
🚀 [ASGI] Starting WebSocket server on first request...
🔧 [ASGI] Calling c_client_ws.start_server(host='0.0.0.0', port=XXXX)
✅ [ASGI] WebSocket server started successfully on port XXXX
```

## 测试步骤
1. 访问B-Client的任意HTTP端点
2. 检查Heroku日志是否显示WebSocket服务器启动
3. 测试C-Client连接是否成功

## 关键修改
- WebSocket服务器现在在第一个HTTP请求时启动
- 使用`ASGIAppWithWebSocket`包装器确保启动顺序
- 添加了详细的调试日志
