# Cashify Deployment Guide

This guide explains how to deploy the Cashify application to your Hetzner server with automated CI/CD.

## Server Details

- **Host**: 95.217.176.128
- **Username**: root
- **Password**: Cashify7

## Quick Start

The fastest way to get started is to use the automated setup:

```bash
ssh root@95.217.176.128
# Enter password: Cashify7

# Run the automated setup script
cd /opt/cashify
bash scripts/server-setup.sh
```

## Initial Server Setup

### Option 1: Automated Setup (Recommended)

1. SSH into the server:
```bash
ssh root@95.217.176.128
```

2. The GitHub Actions workflow will automatically handle the setup on first deployment, or run manually:
```bash
bash scripts/server-setup.sh
```

This script will:
- Install Docker and Docker Compose
- Configure the firewall (UFW)
- Clone the repository to `/opt/cashify`
- Set up the environment file
- Create necessary directories

### Option 2: Manual Setup

If you prefer manual setup:

```bash
# Install Docker
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Install Docker Compose standalone
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Clone repository
mkdir -p /opt
cd /opt
git clone https://github.com/KibokoDao-Africa/Cashify.git cashify
cd cashify

# Setup environment
cp .env.example .env
nano .env  # Edit with your actual credentials
```

## GitHub Actions CI/CD Setup

### Configure GitHub Secrets

Add these secrets to your GitHub repository (Settings > Secrets and variables > Actions):

| Secret Name | Value | Description |
|------------|-------|-------------|
| `HETZNER_HOST` | `95.217.176.128` | Server IP address |
| `HETZNER_USERNAME` | `root` | SSH username |
| `HETZNER_PASSWORD` | `Cashify7` | SSH password |

### How to Add Secrets

1. Go to your GitHub repository
2. Click **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Add each secret listed above

## Automated Deployment

### How It Works

The deployment automatically triggers on:
- Push to `main` branch
- Manual trigger via GitHub Actions UI

The workflow will:
1. SSH into your Hetzner server using password authentication
2. Install Docker and Docker Compose (if needed)
3. Clone/update the repository
4. Create `.env` file from `.env.example` (if doesn't exist)
5. Build and start Docker containers (PostgreSQL + Application)
6. Clean up old Docker images

### Manual Deployment

Run deployment manually:

```bash
ssh root@95.217.176.128
cd /opt/cashify
bash scripts/deploy.sh
```

Or trigger from GitHub:
- GitHub → Actions → Deploy to Hetzner → Run workflow

## Environment Configuration

### Required Environment Variables

Edit `/opt/cashify/.env` with your actual credentials:

#### PostgreSQL Database
```env
POSTGRES_USER=cashify
POSTGRES_PASSWORD=change_this_password
POSTGRES_DB=cashify
DATABASE_URL=postgresql://cashify:change_this_password@postgres:5432/cashify
```

#### Application
```env
PORT=8000
BASE_URL=http://95.217.176.128:8000
```

#### API Keys
```env
AT_USERNAME=your_africastalking_username
AT_API_KEY=your_africastalking_api_key
FACEBOOK_PAGE_ID=your_facebook_page_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_token
INSTAGRAM_ACCESS_TOKEN=your_token
INSTAGRAM_ACCOUNT_ID=your_account_id
TIKTOK_ACCESS_TOKEN=your_token
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
S3_BUCKET_NAME=cashify-bot
```

## Docker Services

The application runs two containers:

### 1. PostgreSQL Database (cashify-postgres)
- **Port**: 5432
- **User**: cashify (configurable)
- **Database**: cashify
- **Data**: Persisted in `postgres_data` volume

### 2. Cashify Application (cashify)
- **Port**: 8000 (configurable via PORT env)
- **Logs**: `./logs` directory
- **Depends on**: PostgreSQL

## Common Commands

### View logs
```bash
cd /opt/cashify
docker-compose logs -f          # All services
docker-compose logs -f cashify  # Application only
docker-compose logs -f postgres # Database only
```

### Restart services
```bash
cd /opt/cashify
docker-compose restart
```

### Stop all services
```bash
cd /opt/cashify
docker-compose down
```

### Start services
```bash
cd /opt/cashify
docker-compose up -d
```

### Rebuild and restart
```bash
cd /opt/cashify
docker-compose up -d --build
```

### Check container status
```bash
docker-compose ps
docker ps
```

### Access PostgreSQL shell
```bash
docker exec -it cashify-postgres psql -U cashify -d cashify
```

### View disk usage
```bash
docker system df
```

## Database Management

### Create a backup
```bash
docker exec cashify-postgres pg_dump -U cashify cashify > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore from backup
```bash
cat backup_file.sql | docker exec -i cashify-postgres psql -U cashify -d cashify
```

### Access database
```bash
docker exec -it cashify-postgres psql -U cashify -d cashify
```

## Troubleshooting

### Deployment fails
- Check GitHub Actions logs for specific errors
- Verify SSH credentials in GitHub secrets
- Ensure server is accessible

### Docker not found
- The setup script should install Docker automatically
- Manually install if needed: `curl -fsSL https://get.docker.com | sh`

### Port already in use
```bash
docker-compose down
docker ps -a
docker rm -f cashify cashify-postgres
```

### Database connection errors
- Check if PostgreSQL container is running: `docker ps`
- Verify DATABASE_URL in `.env`
- Check logs: `docker-compose logs postgres`

### Application won't start
```bash
# Check logs
docker-compose logs cashify

# Restart services
docker-compose restart

# Rebuild
docker-compose up -d --build
```

### Out of disk space
```bash
# Clean up Docker
docker system prune -a -f --volumes

# Check disk usage
df -h
```

## Monitoring

### GitHub Actions
- Repository → Actions → View workflow runs
- Click on any run to see detailed logs

### Server Monitoring
```bash
# Check all containers
docker ps

# View resource usage
docker stats

# Check system resources
htop  # or top
df -h  # disk space
free -h  # memory
```

## Firewall Configuration

The setup script configures UFW with:
- Port 22 (SSH)
- Port 8000 (Application)
- Port 80 (HTTP)
- Port 443 (HTTPS)

View firewall status:
```bash
ufw status
```

## Accessing the Application

Once deployed, access at:
```
http://95.217.176.128:8000
```

## Security Recommendations

1. **Change default passwords**:
   - PostgreSQL password in `.env`
   - Server root password

2. **Set up SSL/TLS**:
   - Use Let's Encrypt for free SSL certificates
   - Configure nginx as reverse proxy

3. **Use SSH keys** instead of password authentication:
   ```bash
   ssh-keygen -t ed25519
   ssh-copy-id root@95.217.176.128
   ```

4. **Regular backups**:
   - Automate PostgreSQL backups
   - Store backups off-server

5. **Update regularly**:
   ```bash
   apt-get update && apt-get upgrade -y
   ```

6. **Monitor logs** for suspicious activity

## Rollback Procedure

If deployment fails or introduces issues:

```bash
ssh root@95.217.176.128
cd /opt/cashify

# View commit history
git log --oneline

# Rollback to previous commit
git reset --hard <commit-hash>

# Redeploy
docker-compose down
docker-compose up -d --build
```
