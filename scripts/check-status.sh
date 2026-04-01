#!/bin/bash

# Cashify Status Check Script

echo "===== Cashify Application Status ====="
echo ""

cd /opt/cashify 2>/dev/null || cd "$(dirname "$0")/.."

echo "1. Docker Containers:"
echo "--------------------"
docker-compose ps
echo ""

echo "2. Container Health:"
echo "--------------------"
docker ps --filter "name=cashify" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

echo "3. Disk Usage:"
echo "--------------------"
docker system df
echo ""

echo "4. Recent Application Logs (last 20 lines):"
echo "--------------------"
docker-compose logs --tail=20 cashify
echo ""

echo "5. Testing Application Endpoint:"
echo "--------------------"
if curl -f http://localhost:8000 > /dev/null 2>&1; then
    echo "✓ Application is responding on port 8000"
else
    echo "✗ Application is not responding on port 8000"
fi
echo ""

echo "6. Database Connection:"
echo "--------------------"
if docker exec cashify-postgres pg_isready -U cashify > /dev/null 2>&1; then
    echo "✓ PostgreSQL is ready"
else
    echo "✗ PostgreSQL is not ready"
fi
echo ""

echo "===== Status Check Complete ====="
