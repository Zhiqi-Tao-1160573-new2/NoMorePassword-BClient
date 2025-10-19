# B-Client Flask Application

Enterprise-level client for NoMorePassword Backend Service, rebuilt using Flask + Python.

## Features

- **Cookie Management**: Store and manage user cookies with auto-refresh capability
- **Account Management**: Store user account credentials with full details
- **Dashboard Statistics**: Real-time statistics and monitoring
- **Enterprise Security**: Complete data isolation and enhanced security features

## Installation

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python run.py
   ```

3. **Access the application**:
   - Main page: http://localhost:3000
   - Dashboard: http://localhost:3000/dashboard
   - History: http://localhost:3000/history
   - API Health: http://localhost:3000/api/health

## API Endpoints

### Health Check
- `GET /api/health` - Service health status

### Statistics
- `GET /api/stats` - Dashboard statistics

### Configuration
- `GET /api/config` - Application configuration

### Cookie Management
- `GET /api/cookies?user_id=<user_id>` - Get cookies for user
- `POST /api/cookies` - Add or update cookie

### Account Management
- `GET /api/accounts?user_id=<user_id>` - Get accounts for user
- `POST /api/accounts` - Add or update account
- `DELETE /api/accounts/<user_id>/<username>/<website>/<account>` - Delete account

## Database Schema

### user_cookies
- `user_id` (VARCHAR(50), Primary Key)
- `username` (TEXT, Primary Key)
- `node_id` (VARCHAR(50))
- `cookie` (TEXT)
- `auto_refresh` (BOOLEAN)
- `refresh_time` (TIMESTAMP)
- `create_time` (TIMESTAMP)

### user_accounts
- `user_id` (VARCHAR(50), Primary Key)
- `username` (TEXT, Primary Key)
- `website` (TEXT, Primary Key)
- `account` (VARCHAR(50), Primary Key)
- `password` (TEXT)
- `email` (TEXT)
- `first_name` (TEXT)
- `last_name` (TEXT)
- `location` (TEXT)
- `registration_method` (VARCHAR(20))
- `auto_generated` (BOOLEAN)
- `create_time` (TIMESTAMP)

### domain_nodes
**Note: This table has been removed. Domain information is now managed by NodeManager connection pools in memory.**

## Configuration

The application uses `config.json` for configuration. Key settings:

- **Network**: IP address settings for local/public deployment
- **API**: Port configurations for NSN and C-Client services
- **Target Websites**: Website configurations for different environments
- **Auto-refresh**: Default interval for cookie refresh

## Environment Variables

- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 3000)
- `DEBUG`: Debug mode (default: True)

## Development

The application is built with:
- **Flask**: Web framework
- **SQLAlchemy**: Database ORM
- **SQLite**: Database (b_client_secure.db)
- **HTML/CSS/JavaScript**: Frontend

## Security Features

- Complete data isolation
- Enterprise-level security
- Encrypted database storage
- Secure cookie management
- Auto-refresh capabilities

## License

Enterprise-level client for NoMorePassword Backend Service.
