# Deployment Guide - Hetzner Server

This guide explains how to set up automated deployment to your Hetzner server using GitHub Actions.

## Prerequisites

1. A Hetzner server with:
   - Docker and Docker Compose installed
   - Git installed
   - SSH access configured

2. GitHub repository with the code

## Setup Instructions

### 1. Prepare Your Hetzner Server

SSH into your Hetzner server and run:

```bash
# Install Docker (if not already installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose (if not already installed)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create deployment directory
sudo mkdir -p /opt/cashify
sudo chown $USER:$USER /opt/cashify

# Clone your repository
cd /opt/cashify
git clone <your-repo-url> .

# Copy environment file
cp .env.example .env
# Edit .env with your actual values
nano .env
```

### 2. Configure GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

Add the following secrets:

| Secret Name | Description | Example |
|------------|-------------|---------|
| `HETZNER_HOST` | Your Hetzner server IP or domain | `123.456.789.0` |
| `HETZNER_USERNAME` | SSH username (usually `root` or your user) | `root` |
| `HETZNER_SSH_KEY` | Private SSH key for authentication | `-----BEGIN RSA PRIVATE KEY-----...` |
| `HETZNER_PORT` | SSH port (optional, defaults to 22) | `22` |
| `DEPLOY_PATH` | Deployment directory path | `/opt/cashify` |

### 3. Generate SSH Key for GitHub Actions

On your local machine or server:

```bash
# Generate a new SSH key pair
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# Copy the public key to your Hetzner server
ssh-copy-id -i ~/.ssh/github_actions.pub user@your-hetzner-server

# Display the private key to copy to GitHub secrets
cat ~/.ssh/github_actions
```

Copy the entire private key (including `-----BEGIN...` and `-----END...` lines) and add it as `HETZNER_SSH_KEY` in GitHub secrets.

### 4. Test SSH Connection

From your local machine:

```bash
ssh -i ~/.ssh/github_actions user@your-hetzner-server
```

### 5. Deployment Workflow

The deployment will automatically trigger on:
- Push to `main` branch
- Manual trigger via GitHub Actions UI

The workflow will:
1. SSH into your Hetzner server
2. Pull the latest code from the repository
3. Rebuild the Docker container
4. Restart the application
5. Clean up old Docker images

### 6. Manual Deployment

You can also manually deploy by going to:
- GitHub → Actions → Deploy to Hetzner → Run workflow

## Troubleshooting

### Deployment fails with "Permission denied"
- Ensure the SSH key is correctly added to GitHub secrets
- Verify the public key is in `~/.ssh/authorized_keys` on the Hetzner server

### Docker commands fail
- Make sure your user has Docker permissions: `sudo usermod -aG docker $USER`
- Log out and back in for changes to take effect

### Port already in use
- Check if the application is already running: `docker ps`
- Stop the existing container: `docker stop cashify`

### Environment variables not loaded
- Ensure `.env` file exists on the server at `DEPLOY_PATH`
- Verify PORT and other required variables are set

## Monitoring

Check deployment logs in GitHub Actions:
- Go to your repository → Actions → Click on the latest workflow run

Check application logs on the server:
```bash
docker logs cashify -f
```

## Rollback

If deployment fails, you can manually rollback:

```bash
cd /opt/cashify
git reset --hard <previous-commit-hash>
docker-compose up -d --build
```
