# Cashify API Endpoints

Base URL: `http://95.217.176.128:8000`
HTTPS URL: `https://95.217.176.128` (after SSL setup)

**Interactive API Documentation (Swagger):** `/docs`
**API Specification (OpenAPI):** `/apispec.json`

---

## 📚 Swagger Documentation

Access the interactive API documentation at:
- **HTTP:** http://95.217.176.128:8000/docs
- **HTTPS:** https://95.217.176.128/docs (after SSL setup)

The Swagger UI allows you to:
- Browse all available endpoints
- Test API calls directly from your browser
- View request/response schemas
- See example data for each endpoint

---

## Health Check

### GET /
Returns application status and available endpoints.

```bash
curl http://95.217.176.128:8000
```

## Products

### POST /products
Create a new product.

```bash
curl -X POST http://95.217.176.128:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Product Name",
    "price": 100,
    "description": "Product description"
  }'
```

### GET /products
Get all products.

```bash
curl http://95.217.176.128:8000/products
```

### GET /products/:product_id
Get a specific product.

```bash
curl http://95.217.176.128:8000/products/PRODUCT_ID
```

## Fees

### GET /fees
Get all category fees.

```bash
curl http://95.217.176.128:8000/fees
```

### POST /fees
Create or update category fees.

```bash
curl -X POST http://95.217.176.128:8000/fees \
  -H "Content-Type: application/json" \
  -d '{
    "category": "electronics",
    "fee_percentage": 5
  }'
```

## Media Upload

### POST /upload/tiktok
Upload media to TikTok.

```bash
curl -X POST http://95.217.176.128:8000/upload/tiktok \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://example.com/video.mp4",
    "caption": "My video caption"
  }'
```

### POST /upload/instagram
Upload media to Instagram.

```bash
curl -X POST http://95.217.176.128:8000/upload/instagram \
  -H "Content-Type: application/json" \
  -d '{
    "media_url": "https://example.com/image.jpg",
    "caption": "My photo caption"
  }'
```

### POST /upload/facebook
Upload media to Facebook.

```bash
curl -X POST http://95.217.176.128:8000/upload/facebook \
  -H "Content-Type: application/json" \
  -d '{
    "media_url": "https://example.com/image.jpg",
    "message": "My post message"
  }'
```

### POST /upload/all
Upload media to all platforms.

```bash
curl -X POST http://95.217.176.128:8000/upload/all \
  -H "Content-Type: application/json" \
  -d '{
    "media_url": "https://example.com/image.jpg",
    "caption": "Cross-platform post"
  }'
```

## Escrow Payments

### POST /escrow/pay
Create an escrow payment.

```bash
curl -X POST http://95.217.176.128:8000/escrow/pay \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_phone": "+254700000000",
    "seller_phone": "+254700000001",
    "amount": 1000,
    "description": "Payment for product"
  }'
```

### POST /escrow/confirm
Confirm receipt of goods/services.

```bash
curl -X POST http://95.217.176.128:8000/escrow/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "escrow_id": "ESCROW_ID",
    "buyer_phone": "+254700000000"
  }'
```

### POST /escrow/release
Release escrow payment to seller.

```bash
curl -X POST http://95.217.176.128:8000/escrow/release \
  -H "Content-Type: application/json" \
  -d '{
    "escrow_id": "ESCROW_ID"
  }'
```

### GET /escrow/status/:escrow_id
Get escrow payment status.

```bash
curl http://95.217.176.128:8000/escrow/status/ESCROW_ID
```

### POST /escrow/dispute
Raise a dispute on an escrow payment.

```bash
curl -X POST http://95.217.176.128:8000/escrow/dispute \
  -H "Content-Type: application/json" \
  -d '{
    "escrow_id": "ESCROW_ID",
    "buyer_phone": "+254700000000",
    "reason": "Goods not received"
  }'
```

### POST /escrow/refund
Process a refund for an escrow payment.

```bash
curl -X POST http://95.217.176.128:8000/escrow/refund \
  -H "Content-Type: application/json" \
  -d '{
    "escrow_id": "ESCROW_ID",
    "reason": "Cancelled order"
  }'
```

### GET /escrow/buyer/:buyer_phone
Get all escrow payments for a buyer.

```bash
curl http://95.217.176.128:8000/escrow/buyer/+254700000000
```

### GET /escrow/seller/:seller_phone
Get all escrow payments for a seller.

```bash
curl http://95.217.176.128:8000/escrow/seller/+254700000001
```

### POST /escrow/process-auto-releases
Process automatic releases for confirmed payments.

```bash
curl -X POST http://95.217.176.128:8000/escrow/process-auto-releases
```

### POST /escrow/process-expired
Process expired escrow payments.

```bash
curl -X POST http://95.217.176.128:8000/escrow/process-expired
```

## WhatsApp Webhook

### POST /whatsapp
WhatsApp webhook endpoint (used by Twilio).

```bash
curl -X POST http://95.217.176.128:8000/whatsapp \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp:+254700000000&Body=Hello"
```

## Payment Callback

### GET /pesapal-callback
### POST /pesapal-callback
Pesapal payment callback endpoint.

```bash
curl http://95.217.176.128:8000/pesapal-callback?OrderTrackingId=ORDER_ID
```

## Testing All Endpoints

You can use the test script:

```bash
ssh root@95.217.176.128
cd /opt/cashify
bash scripts/test-endpoints.sh
```

Or test from your local machine:

```bash
bash scripts/test-endpoints.sh http://95.217.176.128:8000
```

## Using with Postman or Insomnia

1. Import the base URL: `http://95.217.176.128:8000`
2. Set Content-Type header: `application/json`
3. Use the endpoints listed above

## Example: Testing the Full Flow

```bash
# 1. Check health
curl http://95.217.176.128:8000

# 2. Get all products
curl http://95.217.176.128:8000/products

# 3. Create a product
curl -X POST http://95.217.176.128:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "iPhone 15",
    "price": 50000,
    "category": "electronics",
    "description": "Brand new iPhone 15"
  }'

# 4. Get fees
curl http://95.217.176.128:8000/fees

# 5. Create escrow payment
curl -X POST http://95.217.176.128:8000/escrow/pay \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_phone": "+254712345678",
    "seller_phone": "+254787654321",
    "amount": 50000,
    "description": "iPhone 15 purchase"
  }'
```

## Notes

- All endpoints return JSON responses
- The application uses CORS, so you can call it from web applications
- WhatsApp webhook is configured for Twilio integration
- Pesapal callback handles payment confirmations
