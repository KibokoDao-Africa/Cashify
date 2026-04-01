#!/bin/bash

# Cashify Server Setup Script
# This script sets up a fresh server with all required dependencies

set -e

echo "===== Cashify Server Setup ====="
echo "Starting server setup..."

# Update system packages
echo "Updating system packages..."
apt-get update
apt-get upgrade -y

# Install essential packages
echo "Installing essential packages..."
apt-get install -y ca-certificates curl gnupg lsb-release git ufw

# Install Docker
echo "Installing Docker..."
if ! command -v docker &> /dev/null; then
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker Engine
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Enable and start Docker
    systemctl enable docker
    systemctl start docker

    echo "Docker installed successfully!"
else
    echo "Docker is already installed."
fi

# Install Docker Compose standalone
echo "Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed successfully!"
else
    echo "Docker Compose is already installed."
fi

# Configure firewall
echo "Configuring firewall..."
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8000/tcp  # Application port
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
echo "Firewall configured successfully!"

# Create project directory
PROJECT_DIR="/opt/cashify"
echo "Creating project directory at $PROJECT_DIR..."
mkdir -p $PROJECT_DIR

# Clone repository
echo "Cloning Cashify repository..."
if [ -d "$PROJECT_DIR/.git" ]; then
    echo "Repository already exists, pulling latest changes..."
    cd $PROJECT_DIR
    git pull origin main
else
    cd /opt
    rm -rf cashify
    git clone https://github.com/KibokoDao-Africa/Cashify.git cashify
    cd $PROJECT_DIR
fi

# Create .env file
echo "Setting up environment file..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp .env.example .env
    echo "Created .env file from .env.example"
    echo "IMPORTANT: Please edit /opt/cashify/.env with your actual credentials!"
else
    echo ".env file already exists."
fi

# Create logs directory
mkdir -p $PROJECT_DIR/logs

# Set proper permissions
chown -R root:root $PROJECT_DIR
chmod -R 755 $PROJECT_DIR

echo ""
echo "===== Server Setup Complete! ====="
echo ""
echo "Next steps:"
echo "1. Edit the .env file: nano /opt/cashify/.env"
echo "2. Add your actual API keys and credentials"
echo "3. Start the application: cd /opt/cashify && docker-compose up -d"
echo "4. Check logs: docker-compose logs -f"
echo ""
echo "The application will be available at: http://your-server-ip:8000"
echo ""
