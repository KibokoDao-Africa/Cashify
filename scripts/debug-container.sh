#!/bin/bash

# Debug script to check container issues

echo "===== Container Debug Info ====="
echo ""

echo "1. Container Status:"
echo "-------------------"
docker ps -a | grep cashify
echo ""

echo "2. Last 50 lines of application logs:"
echo "--------------------------------------"
docker logs cashify --tail=50
echo ""

echo "3. PostgreSQL Status:"
echo "---------------------"
docker logs cashify-postgres --tail=20
echo ""

echo "4. Environment Variables (sanitized):"
echo "--------------------------------------"
docker exec cashify env | grep -v "KEY\|TOKEN\|SECRET\|PASSWORD" || echo "Container not running, cannot check env vars"
echo ""

echo "5. Port Binding:"
echo "----------------"
netstat -tulpn | grep :8000 || ss -tulpn | grep :8000
echo ""
