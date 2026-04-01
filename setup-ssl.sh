#!/bin/bash
# SSL Setup Script for Cashify Production Server
# Run this script on the production server (95.217.176.128) as root

set -e  # Exit on error

echo "=========================================="
echo "Cashify SSL Setup Script"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run this script as root (use sudo)"
    exit 1
fi

# Variables - UPDATE THESE BEFORE RUNNING
DOMAIN="cashify.yourdomain.com"  # Replace with your actual domain
EMAIL="your-email@example.com"   # Replace with your email for Let's Encrypt
APP_DIR="/opt/cashify"
SERVER_IP="95.217.176.128"

echo "Configuration:"
echo "  Domain: $DOMAIN"
echo "  Email: $EMAIL"
echo "  App Directory: $APP_DIR"
echo "  Server IP: $SERVER_IP"
echo ""
read -p "Is this configuration correct? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Please edit this script and update the variables at the top."
    exit 1
fi

# Step 1: Update system packages
echo "Step 1: Updating system packages..."
apt-get update
apt-get upgrade -y

# Step 2: Install Nginx
echo "Step 2: Installing Nginx..."
apt-get install -y nginx

# Step 3: Install Certbot for Let's Encrypt
echo "Step 3: Installing Certbot..."
apt-get install -y certbot python3-certbot-nginx

# Step 4: Configure firewall
echo "Step 4: Configuring firewall..."
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

# Step 5: Create nginx configuration
echo "Step 5: Creating Nginx configuration..."
cat > /etc/nginx/sites-available/cashify << 'EOF'
# Nginx configuration for Cashify API with SSL
server {
    listen 80;
    listen [::]:80;
    server_name SERVER_NAME_PLACEHOLDER;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$server_name$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name SERVER_NAME_PLACEHOLDER;

    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/chain.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets off;

    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    access_log /var/log/nginx/cashify-access.log;
    error_log /var/log/nginx/cashify-error.log;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_buffering off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
}
EOF

# Replace placeholders
sed -i "s/SERVER_NAME_PLACEHOLDER/$DOMAIN $SERVER_IP/g" /etc/nginx/sites-available/cashify
sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" /etc/nginx/sites-available/cashify

# Step 6: Enable the site
echo "Step 6: Enabling Nginx site..."
ln -sf /etc/nginx/sites-available/cashify /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Step 7: Test Nginx configuration
echo "Step 7: Testing Nginx configuration..."
nginx -t

# Step 8: Reload Nginx
echo "Step 8: Reloading Nginx..."
systemctl reload nginx

# Step 9: Obtain SSL certificate
echo "Step 9: Obtaining SSL certificate from Let's Encrypt..."
echo "This may take a few moments..."

# First, temporarily update nginx config to work without SSL
cat > /etc/nginx/sites-available/cashify-temp << 'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name SERVER_NAME_PLACEHOLDER;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sed -i "s/SERVER_NAME_PLACEHOLDER/$DOMAIN $SERVER_IP/g" /etc/nginx/sites-available/cashify-temp
ln -sf /etc/nginx/sites-available/cashify-temp /etc/nginx/sites-enabled/cashify
nginx -t && systemctl reload nginx

# Obtain certificate
certbot certonly --webroot -w /var/www/html -d $DOMAIN --non-interactive --agree-tos --email $EMAIL

# Restore full nginx config with SSL
ln -sf /etc/nginx/sites-available/cashify /etc/nginx/sites-enabled/cashify
nginx -t && systemctl reload nginx

# Step 10: Setup auto-renewal
echo "Step 10: Setting up automatic SSL renewal..."
systemctl enable certbot.timer
systemctl start certbot.timer

# Test renewal
certbot renew --dry-run

# Step 11: Update application environment
echo "Step 11: Updating application configuration..."
if [ -f "$APP_DIR/.env" ]; then
    # Add or update SWAGGER_HOST in .env
    if grep -q "SWAGGER_HOST" "$APP_DIR/.env"; then
        sed -i "s|SWAGGER_HOST=.*|SWAGGER_HOST=$DOMAIN|g" "$APP_DIR/.env"
    else
        echo "SWAGGER_HOST=$DOMAIN" >> "$APP_DIR/.env"
    fi
fi

# Step 12: Restart application
echo "Step 12: Restarting application..."
if systemctl is-active --quiet cashify; then
    systemctl restart cashify
else
    echo "Warning: cashify service not found. Please restart your application manually."
fi

echo ""
echo "=========================================="
echo "SSL Setup Complete!"
echo "=========================================="
echo ""
echo "Your API is now accessible via HTTPS:"
echo "  https://$DOMAIN"
echo "  https://$SERVER_IP"
echo ""
echo "Swagger documentation is available at:"
echo "  https://$DOMAIN/docs"
echo "  https://$SERVER_IP/docs"
echo ""
echo "SSL certificate will auto-renew every 90 days."
echo "You can manually renew with: certbot renew"
echo ""
echo "Important: Make sure your DNS records point to $SERVER_IP"
echo ""
