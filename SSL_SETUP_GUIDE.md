# SSL Configuration Guide for Cashify Production Server

This guide will help you set up SSL/HTTPS for the Cashify API running on the production server at `95.217.176.128:8000`.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Setup (Automated)](#quick-setup-automated)
3. [Manual Setup](#manual-setup)
4. [Testing SSL Configuration](#testing-ssl-configuration)
5. [Swagger Documentation Access](#swagger-documentation-access)
6. [Troubleshooting](#troubleshooting)
7. [Maintenance](#maintenance)

---

## Prerequisites

Before setting up SSL, ensure you have:

- **Root access** to the production server (95.217.176.128)
- **Domain name** (optional but recommended) - e.g., `api.cashify.com`
  - If using a domain, ensure DNS A record points to `95.217.176.128`
- **SSH access** to the server
- **Port 80 and 443** open in firewall

### Required Software

The setup script will install these automatically:
- Nginx (reverse proxy server)
- Certbot (Let's Encrypt SSL certificate manager)
- UFW (Uncomplicated Firewall)

---

## Quick Setup (Automated)

### Step 1: Connect to Production Server

```bash
ssh root@95.217.176.128
```

### Step 2: Navigate to Application Directory

```bash
cd /opt/cashify  # or wherever your app is installed
```

### Step 3: Upload Setup Files

Transfer the following files to your server:
- `setup-ssl.sh` - Automated setup script
- `nginx-ssl.conf` - Nginx configuration template

```bash
# On your local machine:
scp setup-ssl.sh root@95.217.176.128:/opt/cashify/
scp nginx-ssl.conf root@95.217.176.128:/opt/cashify/
```

### Step 4: Edit Configuration

```bash
nano setup-ssl.sh
```

Update these variables:
```bash
DOMAIN="api.cashify.com"           # Your domain (or use IP if no domain)
EMAIL="admin@cashify.com"          # Your email for SSL notifications
APP_DIR="/opt/cashify"             # Your app directory
SERVER_IP="95.217.176.128"         # Your server IP
```

### Step 5: Run Setup Script

```bash
chmod +x setup-ssl.sh
sudo ./setup-ssl.sh
```

The script will:
1. Install Nginx and Certbot
2. Configure firewall
3. Set up Nginx as reverse proxy
4. Obtain SSL certificate from Let's Encrypt
5. Configure auto-renewal
6. Restart services

---

## Manual Setup

If you prefer to set up SSL manually or the automated script fails, follow these steps:

### Step 1: Install Required Packages

```bash
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

### Step 2: Configure Firewall

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

### Step 3: Create Nginx Configuration

Create a new file at `/etc/nginx/sites-available/cashify`:

```bash
sudo nano /etc/nginx/sites-available/cashify
```

Paste the contents from `nginx-ssl.conf` (provided in this repository).

**Important:** Update these placeholders in the file:
- Replace `cashify.yourdomain.com` with your actual domain (or IP address)
- Replace paths to SSL certificates if needed

### Step 4: Enable Nginx Site

```bash
sudo ln -s /etc/nginx/sites-available/cashify /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default  # Remove default site
sudo nginx -t  # Test configuration
sudo systemctl reload nginx
```

### Step 5: Obtain SSL Certificate

#### Option A: Using a Domain Name

```bash
sudo certbot --nginx -d api.cashify.com
```

#### Option B: Using IP Address Only

For IP-only SSL (not recommended for production):
```bash
# You'll need to use a self-signed certificate
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/cashify-selfsigned.key \
  -out /etc/ssl/certs/cashify-selfsigned.crt
```

Then update the nginx config to point to these files:
```nginx
ssl_certificate /etc/ssl/certs/cashify-selfsigned.crt;
ssl_certificate_key /etc/ssl/private/cashify-selfsigned.key;
```

### Step 6: Update Application Configuration

Update your `.env` file to reflect HTTPS:

```bash
cd /opt/cashify
nano .env
```

Add or update:
```
SWAGGER_HOST=api.cashify.com
# or if using IP: SWAGGER_HOST=95.217.176.128
```

### Step 7: Restart Services

```bash
sudo systemctl restart nginx
sudo systemctl restart cashify  # or your app service name
```

---

## Testing SSL Configuration

### 1. Test SSL Certificate

```bash
# Check certificate details
echo | openssl s_client -connect api.cashify.com:443 2>/dev/null | openssl x509 -noout -dates

# Test SSL connection
curl -I https://api.cashify.com
```

### 2. Test API Endpoints

```bash
# Health check
curl https://api.cashify.com/

# Get products
curl https://api.cashify.com/products

# Get fees
curl https://api.cashify.com/fees
```

### 3. Verify HTTP to HTTPS Redirect

```bash
curl -I http://api.cashify.com
# Should return 301 redirect to https://
```

### 4. SSL Labs Test

Visit [SSL Labs](https://www.ssllabs.com/ssltest/) and test your domain for SSL configuration quality.

---

## Swagger Documentation Access

Once SSL is configured, access Swagger documentation at:

**With Domain:**
- https://api.cashify.com/docs

**With IP:**
- https://95.217.176.128/docs

### Swagger Features

The Swagger UI provides:
- **Interactive API testing** - Try out endpoints directly from browser
- **Complete API documentation** - All endpoints, parameters, and responses
- **Request/Response examples** - See example data for each endpoint
- **Authentication testing** - Test authenticated endpoints

### API Spec

The OpenAPI specification is available at:
- https://api.cashify.com/apispec.json

---

## Troubleshooting

### Issue: "Connection Refused" on HTTPS

**Solution:**
```bash
# Check if Nginx is running
sudo systemctl status nginx

# Check if port 443 is listening
sudo netstat -tlnp | grep :443

# Check Nginx error logs
sudo tail -f /var/log/nginx/cashify-error.log
```

### Issue: SSL Certificate Errors

**Solution:**
```bash
# Verify certificate files exist
ls -la /etc/letsencrypt/live/*/

# Test certificate renewal
sudo certbot renew --dry-run

# Check certificate expiry
sudo certbot certificates
```

### Issue: 502 Bad Gateway

**Solution:**
```bash
# Check if Flask app is running
sudo systemctl status cashify

# Check app logs
sudo journalctl -u cashify -f

# Verify app is listening on port 8000
sudo netstat -tlnp | grep :8000

# Test direct connection
curl http://localhost:8000
```

### Issue: Swagger Docs Not Loading

**Solution:**
```bash
# Check if flasgger is installed
pip list | grep flasgger

# Verify Swagger routes in nginx
sudo nginx -T | grep -A 5 "location /docs"

# Check Flask logs
sudo journalctl -u cashify | grep swagger
```

### Issue: Certificate Auto-Renewal Failed

**Solution:**
```bash
# Check certbot timer status
sudo systemctl status certbot.timer

# Manually renew certificate
sudo certbot renew

# Check renewal logs
sudo cat /var/log/letsencrypt/letsencrypt.log
```

---

## Maintenance

### SSL Certificate Renewal

Let's Encrypt certificates expire after 90 days. Auto-renewal is configured, but you can manually renew:

```bash
# Dry run (test renewal without actually renewing)
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check certificate expiry dates
sudo certbot certificates
```

### Monitoring SSL Certificate Expiry

Set up monitoring alerts:

```bash
# Add to crontab for weekly checks
crontab -e

# Add this line:
0 0 * * 0 certbot renew --post-hook "systemctl reload nginx"
```

### Nginx Configuration Updates

After making changes to Nginx config:

```bash
# Test configuration
sudo nginx -t

# Reload Nginx (zero downtime)
sudo systemctl reload nginx

# Or restart Nginx (brief downtime)
sudo systemctl restart nginx
```

### Updating Security Headers

The nginx configuration includes modern security headers. To update:

```bash
sudo nano /etc/nginx/sites-available/cashify
# Make changes
sudo nginx -t
sudo systemctl reload nginx
```

### Backup SSL Certificates

```bash
# Backup Let's Encrypt directory
sudo tar -czf letsencrypt-backup-$(date +%Y%m%d).tar.gz /etc/letsencrypt/

# Store backup securely off-server
```

---

## Security Best Practices

1. **Keep Software Updated**
   ```bash
   sudo apt-get update && sudo apt-get upgrade
   ```

2. **Monitor Access Logs**
   ```bash
   sudo tail -f /var/log/nginx/cashify-access.log
   ```

3. **Enable Fail2ban** (optional but recommended)
   ```bash
   sudo apt-get install fail2ban
   sudo systemctl enable fail2ban
   ```

4. **Regular Security Audits**
   - Use [SSL Labs](https://www.ssllabs.com/ssltest/)
   - Run security scans with tools like `nmap` or `nikto`

5. **Monitor Certificate Expiry**
   - Set up monitoring alerts (e.g., UptimeRobot, Pingdom)
   - Check certificates monthly

---

## Additional Resources

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Nginx SSL Configuration Guide](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [Certbot Documentation](https://certbot.eff.org/docs/)

---

## Support

If you encounter issues not covered in this guide:

1. Check application logs: `sudo journalctl -u cashify -f`
2. Check Nginx logs: `sudo tail -f /var/log/nginx/cashify-error.log`
3. Verify DNS configuration
4. Ensure firewall allows ports 80 and 443
5. Contact your system administrator

---

## Quick Reference

### Useful Commands

```bash
# Check SSL certificate details
sudo certbot certificates

# Renew SSL certificate
sudo certbot renew

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx

# Restart application
sudo systemctl restart cashify

# View application logs
sudo journalctl -u cashify -f

# View Nginx logs
sudo tail -f /var/log/nginx/cashify-error.log

# Check what's listening on ports
sudo netstat -tlnp | grep -E '(:80|:443|:8000)'
```

---

**Last Updated:** 2026-04-01
**Version:** 1.0.0
