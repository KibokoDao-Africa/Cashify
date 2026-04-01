# Cashify API - SSL & Swagger Setup Summary

## Overview

This document summarizes the SSL certificate configuration and Swagger documentation setup for the Cashify API running on production server `95.217.176.128:8000`.

---

## What Was Done

### 1. Swagger API Documentation Setup ✅

Added comprehensive interactive API documentation using Flasgger (Swagger UI).

**Changes Made:**
- ✅ Added `flasgger==0.9.7.1` to `requirements.txt`
- ✅ Integrated Swagger into Flask application (`app.py`)
- ✅ Configured Swagger UI with custom branding and metadata
- ✅ Added detailed API documentation to all major endpoints:
  - Health check endpoint
  - Products endpoints (GET, POST, GET by ID)
  - Fees endpoint (GET/POST)
  - Social media upload endpoints (TikTok, Instagram, Facebook, All)
  - Escrow payment endpoints (Pay, Confirm, Status, Dispute, Release, Refund)
  - Buyer/Seller escrow history endpoints
  - Admin endpoints for auto-releases and expired payments

**Access Swagger Documentation:**
```
http://95.217.176.128:8000/docs
https://95.217.176.128/docs (after SSL setup)
```

**API Specification JSON:**
```
http://95.217.176.128:8000/apispec.json
```

### 2. SSL Certificate Configuration 🔒

Created comprehensive SSL setup files for securing the API with HTTPS.

**Files Created:**

1. **`nginx-ssl.conf`** - Production-ready Nginx configuration
   - HTTP to HTTPS redirect
   - Modern SSL/TLS configuration (TLS 1.2 & 1.3)
   - Security headers (HSTS, X-Frame-Options, etc.)
   - Optimized SSL ciphers
   - OCSP stapling
   - Reverse proxy to Flask app on port 8000
   - Support for large file uploads (100MB)
   - Dedicated routes for Swagger documentation

2. **`setup-ssl.sh`** - Automated SSL setup script
   - Installs Nginx and Certbot
   - Configures firewall (UFW)
   - Sets up reverse proxy
   - Obtains Let's Encrypt SSL certificate
   - Configures automatic certificate renewal
   - Updates application configuration

3. **`SSL_SETUP_GUIDE.md`** - Comprehensive setup guide
   - Prerequisites and requirements
   - Quick setup instructions (automated)
   - Manual setup steps
   - Testing procedures
   - Troubleshooting guide
   - Maintenance instructions
   - Security best practices

### 3. Documentation Updates 📝

**Updated `API_ENDPOINTS.md`:**
- Added Swagger documentation links
- Added HTTPS base URL
- Added interactive documentation information

---

## Next Steps - Deploying to Production

### Prerequisites

Before deploying, ensure you have:
1. ✅ SSH access to production server (95.217.176.128)
2. ✅ Root/sudo privileges on the server
3. ⚠️ (Optional) A domain name pointing to 95.217.176.128
   - If you have a domain (e.g., `api.cashify.com`), update its A record to point to `95.217.176.128`
4. ✅ Ports 80 and 443 open on the server

### Quick Deployment Guide

#### Step 1: Install Dependencies on Production

SSH into your production server and install the new Python dependency:

```bash
ssh root@95.217.176.128
cd /opt/cashify  # or your app directory
source venv/bin/activate  # activate virtual environment
pip install flasgger==0.9.7.1
```

#### Step 2: Update Application Code

Deploy the updated `app.py` and `requirements.txt` to production:

```bash
# On your local machine, copy updated files
scp app.py root@95.217.176.128:/opt/cashify/
scp requirements.txt root@95.217.176.128:/opt/cashify/
```

#### Step 3: Restart Application

```bash
# On production server
sudo systemctl restart cashify  # or your service name
# OR if running with gunicorn manually:
pkill gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

#### Step 4: Verify Swagger Documentation

Test that Swagger is working:

```bash
curl http://95.217.176.128:8000/docs
# Should return HTML for Swagger UI

curl http://95.217.176.128:8000/apispec.json
# Should return JSON API specification
```

Visit in browser:
- http://95.217.176.128:8000/docs

#### Step 5: Setup SSL Certificate

**Option A: Automated Setup (Recommended)**

1. Copy SSL setup files to production:
   ```bash
   scp setup-ssl.sh root@95.217.176.128:/opt/cashify/
   scp nginx-ssl.conf root@95.217.176.128:/opt/cashify/
   scp SSL_SETUP_GUIDE.md root@95.217.176.128:/opt/cashify/
   ```

2. SSH into production server:
   ```bash
   ssh root@95.217.176.128
   cd /opt/cashify
   ```

3. Edit the setup script:
   ```bash
   nano setup-ssl.sh
   ```

   Update these variables:
   ```bash
   DOMAIN="api.cashify.com"      # Your domain OR "95.217.176.128" if no domain
   EMAIL="your-email@example.com" # Your email for SSL notifications
   APP_DIR="/opt/cashify"         # Your application directory
   SERVER_IP="95.217.176.128"     # Keep this as is
   ```

4. Run the setup script:
   ```bash
   chmod +x setup-ssl.sh
   sudo ./setup-ssl.sh
   ```

**Option B: Manual Setup**

Follow the detailed manual setup instructions in `SSL_SETUP_GUIDE.md`.

#### Step 6: Test HTTPS

After SSL setup completes:

```bash
# Test health endpoint
curl https://95.217.176.128/
# or with domain:
curl https://api.cashify.com/

# Test Swagger UI
curl https://95.217.176.128/docs

# Test API endpoints
curl https://95.217.176.128/products
curl https://95.217.176.128/fees
```

Visit in browser:
- https://95.217.176.128/docs
- https://api.cashify.com/docs (if using domain)

---

## Features Added

### Swagger Documentation Features

1. **Interactive API Testing**
   - Test all API endpoints directly from the browser
   - No need for external tools like Postman or cURL
   - See real-time responses

2. **Complete API Documentation**
   - All endpoints documented with descriptions
   - Request parameter specifications
   - Response schema definitions
   - Example values for all fields

3. **Organized by Tags**
   - Health - Health check endpoints
   - Products - Product management
   - Fees - Category fee management
   - Social Media - Upload endpoints
   - Escrow - Payment and escrow management
   - WhatsApp - Webhook endpoint
   - Payment - Payment callbacks

4. **OpenAPI Specification**
   - Standard OpenAPI 2.0 (Swagger) format
   - Can be imported into any API client
   - Useful for code generation

### SSL/HTTPS Features

1. **Secure Communication**
   - All API traffic encrypted with TLS 1.2/1.3
   - Modern cipher suites
   - Perfect Forward Secrecy

2. **Security Headers**
   - HSTS (HTTP Strict Transport Security)
   - X-Frame-Options
   - X-Content-Type-Options
   - X-XSS-Protection

3. **Auto-Renewal**
   - SSL certificates automatically renew every 90 days
   - Zero-downtime renewal process
   - Email notifications for renewal issues

4. **HTTP to HTTPS Redirect**
   - All HTTP traffic automatically redirected to HTTPS
   - Clients always use secure connection

---

## Configuration Details

### Environment Variables

Update your `.env` file with:

```bash
# For Swagger to show correct URLs
SWAGGER_HOST=api.cashify.com  # or 95.217.176.128 if using IP only
```

### Nginx Configuration

The nginx configuration includes:
- Reverse proxy to Flask app on `127.0.0.1:8000`
- SSL termination
- Large file upload support (100MB)
- Long timeout for slow requests (10 minutes)
- Websocket support
- Static file serving for Swagger UI

### Service Architecture

```
Client (HTTPS)
    ↓
Nginx (Port 443) - SSL Termination
    ↓
Flask App (Port 8000) - HTTP
    ↓
MongoDB, AWS S3, Payment APIs, etc.
```

---

## Testing Checklist

Before considering deployment complete, test:

- [ ] Swagger UI loads at `/docs`
- [ ] API spec JSON available at `/apispec.json`
- [ ] All endpoints documented in Swagger
- [ ] Can test API calls from Swagger UI
- [ ] HTTP redirects to HTTPS
- [ ] SSL certificate is valid
- [ ] All API endpoints work over HTTPS
- [ ] Health check endpoint responds
- [ ] Products endpoints work (GET, POST)
- [ ] Fees endpoint works
- [ ] Upload endpoints accessible
- [ ] Escrow endpoints accessible
- [ ] Certificate auto-renewal configured
- [ ] Nginx logs being written
- [ ] Application logs being written

---

## File Changes Summary

### Modified Files:
- `requirements.txt` - Added flasgger dependency
- `app.py` - Added Swagger configuration and endpoint documentation
- `API_ENDPOINTS.md` - Updated with Swagger links and HTTPS URLs

### New Files:
- `nginx-ssl.conf` - Nginx configuration with SSL
- `setup-ssl.sh` - Automated SSL setup script (executable)
- `SSL_SETUP_GUIDE.md` - Comprehensive SSL setup guide
- `SETUP_SUMMARY.md` - This file

---

## Troubleshooting

### Swagger Not Loading

1. Check flasgger is installed:
   ```bash
   pip list | grep flasgger
   ```

2. Check Flask logs:
   ```bash
   sudo journalctl -u cashify -f
   ```

3. Test endpoint directly:
   ```bash
   curl http://127.0.0.1:8000/docs
   ```

### SSL Certificate Issues

1. Check certificate status:
   ```bash
   sudo certbot certificates
   ```

2. Test certificate renewal:
   ```bash
   sudo certbot renew --dry-run
   ```

3. Check Nginx configuration:
   ```bash
   sudo nginx -t
   ```

### 502 Bad Gateway

1. Check if Flask app is running:
   ```bash
   sudo systemctl status cashify
   ps aux | grep gunicorn
   ```

2. Check if app is listening on port 8000:
   ```bash
   sudo netstat -tlnp | grep :8000
   ```

3. Test direct connection:
   ```bash
   curl http://127.0.0.1:8000/
   ```

---

## Maintenance

### Regular Tasks

1. **Monitor SSL Certificate Expiry**
   ```bash
   sudo certbot certificates
   ```

2. **Check Nginx Logs**
   ```bash
   sudo tail -f /var/log/nginx/cashify-access.log
   sudo tail -f /var/log/nginx/cashify-error.log
   ```

3. **Update Dependencies**
   ```bash
   pip install --upgrade flasgger
   ```

4. **Keep System Updated**
   ```bash
   sudo apt-get update && sudo apt-get upgrade
   ```

---

## Security Recommendations

1. ✅ SSL/TLS encryption enabled
2. ✅ Modern security headers configured
3. ✅ Auto-renewal for certificates
4. ⚠️ Consider adding rate limiting (e.g., with nginx-limit-req)
5. ⚠️ Consider adding API authentication for sensitive endpoints
6. ⚠️ Set up monitoring/alerting for certificate expiry
7. ⚠️ Regular security audits with SSL Labs
8. ⚠️ Consider adding fail2ban for brute force protection

---

## Additional Resources

- **Swagger Documentation:** http://95.217.176.128:8000/docs
- **SSL Setup Guide:** `SSL_SETUP_GUIDE.md`
- **API Endpoints Reference:** `API_ENDPOINTS.md`
- **Flasgger Documentation:** https://github.com/flasgger/flasgger
- **Let's Encrypt:** https://letsencrypt.org/
- **Nginx SSL Guide:** https://nginx.org/en/docs/http/configuring_https_servers.html

---

## Support & Questions

For issues or questions:
1. Check the `SSL_SETUP_GUIDE.md` troubleshooting section
2. Review application logs: `sudo journalctl -u cashify -f`
3. Review Nginx logs: `sudo tail -f /var/log/nginx/cashify-error.log`
4. Test SSL configuration: https://www.ssllabs.com/ssltest/

---

**Setup Completed:** 2026-04-01
**Version:** 1.0.0
**Status:** Ready for Production Deployment
