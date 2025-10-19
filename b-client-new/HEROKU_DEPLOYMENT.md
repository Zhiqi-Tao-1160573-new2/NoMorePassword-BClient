# B-Client Heroku Deployment Guide

## 🚀 Quick Deployment Steps

### 1. **Prepare for Deployment**
```bash
cd src/main/b-client-new
git init
git add .
git commit -m "Initial commit for Heroku deployment"
```

### 2. **Create Heroku App**
```bash
# Install Heroku CLI first: https://devcenter.heroku.com/articles/heroku-cli
heroku create nomorepassword-bclient
```

### 3. **Set Environment Variables**
```bash
# Set production environment
heroku config:set B_CLIENT_ENVIRONMENT=production

# Set NSN URL
heroku config:set NSN_URL=https://comp693nsnproject.pythonanywhere.com

# Database is automatically configured with SQLite
# No additional database configuration needed

# Optional: Set debug mode
heroku config:set DEBUG=False
```

### 4. **Deploy to Heroku**
```bash
git push heroku main
```

### 5. **Verify Deployment**
```bash
# Check app status
heroku ps

# View logs
heroku logs --tail

# Open app in browser
heroku open
```

## 🔧 Configuration Details

### **Environment Variables**
- `B_CLIENT_ENVIRONMENT`: Set to `production` for production deployment
- `NSN_URL`: Your NSN server URL (e.g., `https://comp693nsnproject.pythonanywhere.com`)
- `HOST`: Server host (default: `0.0.0.0`)
- `PORT`: Server port (Heroku sets this automatically)
- `DEBUG`: Debug mode (set to `False` for production)

### **Database Configuration**
The app uses **SQLite** with SQLAlchemy ORM:
- ✅ **No external database required**
- ✅ **Uses Python standard library sqlite3**
- ✅ **Automatic database initialization**
- ✅ **Persistent storage on Heroku dyno**
- ✅ **No additional configuration needed**

## 🌐 WebSocket Support

Heroku supports WebSockets on all dyno types. Your B-Client will be accessible at:
- **HTTP**: `https://nomorepassword-bclient.herokuapp.com`
- **WebSocket**: `wss://nomorepassword-bclient.herokuapp.com/ws`

## 📊 Monitoring

### **View Logs**
```bash
heroku logs --tail
```

### **Check App Status**
```bash
heroku ps
```

### **Restart App**
```bash
heroku restart
```

## 🔒 Security Considerations

1. **Environment Variables**: Never commit sensitive data to git
2. **HTTPS**: Heroku provides automatic SSL certificates
3. **CORS**: Configure CORS for your NSN and C-Client domains
4. **Database**: Use Heroku Postgres for production or external MySQL

## 🐛 Troubleshooting

### **Common Issues**

1. **WebSocket Connection Failed**
   - Check if WebSocket endpoint is accessible
   - Verify CORS configuration
   - Check Heroku logs for errors

2. **Database Connection Error**
   - Check if SQLite database file is accessible
   - Verify file permissions on Heroku dyno
   - Check database initialization logs

3. **App Crashes on Startup**
   - Check Heroku logs: `heroku logs --tail`
   - Verify all dependencies are in requirements.txt
   - Check environment variables

### **Debug Commands**
```bash
# Check app status
heroku ps

# View recent logs
heroku logs --tail

# Run one-off dyno for debugging
heroku run bash

# Check environment variables
heroku config
```

## 📈 Scaling

### **Upgrade Dyno Type**
```bash
# For better performance
heroku ps:scale web=1:standard-1x

# For high availability
heroku ps:scale web=2:standard-1x
```

### **Database Storage**
```bash
# SQLite uses local file storage
# No additional addons needed
# Database persists on dyno restart
```

## 🔄 Updates

### **Deploy Updates**
```bash
git add .
git commit -m "Update B-Client"
git push heroku main
```

### **Rollback**
```bash
heroku rollback
```

## 📞 Support

- **Heroku Documentation**: https://devcenter.heroku.com/
- **Flask on Heroku**: https://devcenter.heroku.com/articles/getting-started-with-python
- **WebSocket on Heroku**: https://devcenter.heroku.com/articles/websockets
