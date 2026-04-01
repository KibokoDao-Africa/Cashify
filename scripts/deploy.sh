#!/bin/bash

# Cashify Deployment Script
# This script handles deployment updates

set -e

PROJECT_DIR="/opt/cashify"

echo "===== Cashify Deployment ====="
echo "Starting deployment process..."

# Navigate to project directory
cd $PROJECT_DIR

# Pull latest changes
echo "Pulling latest changes from git..."
git fetch origin
git reset --hard origin/main

# Stop existing containers
echo "Stopping existing containers..."
docker-compose down || true

# Build and start containers
echo "Building and starting containers..."
docker-compose up -d --build

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 15

# Check container status
echo "Container status:"
docker-compose ps

# Show recent logs
echo ""
echo "Recent logs:"
docker-compose logs --tail=50

# Clean up old images
echo ""
echo "Cleaning up old Docker images..."
docker image prune -f

echo ""
echo "===== Deployment Complete! ====="
echo ""
echo "Application is running!"
echo "Check logs: docker-compose logs -f"
echo "Stop application: docker-compose down"
echo ""
