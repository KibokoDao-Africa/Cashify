#!/bin/bash

# Force rebuild script - fixes pkg_resources error
# This ensures a complete rebuild with latest code

set -e

echo "===== Force Rebuild - Fixing pkg_resources Error ====="
echo ""

cd /opt/cashify

echo "1. Pulling latest code from git..."
git fetch origin
git reset --hard origin/main
echo "✓ Code updated"
echo ""

echo "2. Checking requirements.txt for setuptools..."
if grep -q "setuptools" requirements.txt; then
    echo "✓ setuptools found in requirements.txt"
else
    echo "✗ setuptools NOT found in requirements.txt"
    echo "Adding setuptools to requirements.txt..."
    sed -i '/pymongo/a setuptools>=65.0.0' requirements.txt
fi
echo ""

echo "3. Stopping all containers..."
docker-compose down
echo "✓ Containers stopped"
echo ""

echo "4. Removing old images..."
docker rmi cashify-cashify 2>/dev/null || echo "Image already removed or doesn't exist"
docker image prune -f
echo "✓ Old images removed"
echo ""

echo "5. Rebuilding with no cache (this may take a few minutes)..."
docker-compose build --no-cache --progress=plain
echo "✓ Build complete"
echo ""

echo "6. Starting containers..."
docker-compose up -d
echo "✓ Containers started"
echo ""

echo "7. Waiting for services to start..."
sleep 15
echo ""

echo "8. Checking container status..."
docker-compose ps
echo ""

echo "9. Checking application logs..."
docker logs cashify --tail=20
echo ""

echo "10. Testing health endpoint..."
sleep 5
if curl -f http://localhost:8000 2>/dev/null; then
    echo ""
    echo "===== SUCCESS! ====="
    echo "Application is running and responding!"
else
    echo ""
    echo "===== WARNING ====="
    echo "Application may still be starting up. Check logs with:"
    echo "docker logs cashify -f"
fi
echo ""
