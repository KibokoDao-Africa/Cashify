# Changelog

All notable changes to the Cashify/Own Again project are documented here.

---

## [2024-03-27] - Escrow Service & Social Media Upload APIs

### Added

#### Escrow Payment Service (`escrow_service.py`)

A complete escrow payment system that allows buyers to pay securely for items with funds held until delivery is confirmed.

**Features:**
- Buyer pays via STK Push (Pesapal) to business account
- System maps payment to seller and product
- Money held in escrow until buyer confirms receipt
- Automatic payout to seller's M-Pesa on confirmation
- Dispute handling and refund processing
- Auto-release after 7-day confirmation window
- WhatsApp notifications to buyer and seller

**Escrow Statuses:**
| Status | Description |
|--------|-------------|
| `pending` | Payment initiated, waiting for buyer |
| `paid` | Funds received and held in escrow |
| `confirmed` | Buyer confirmed receipt |
| `released` | Money sent to seller |
| `disputed` | Buyer raised a dispute |
| `refunded` | Money returned to buyer |
| `cancelled` | Transaction cancelled |
| `expired` | Payment window expired |

---

#### Escrow API Endpoints

##### 1. Create Escrow Payment
```
POST /escrow/pay
```
Initiates STK Push payment for buyer to purchase an item.

**Request:**
```json
{
  "product_id": "507f1f77bcf86cd799439011",
  "buyer_phone": "0712345678",
  "buyer_name": "John Doe"  // optional
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "escrow_id": "507f1f77bcf86cd799439012",
    "payment_url": "https://pay.pesapal.com/...",
    "amount": 1500.00,
    "currency": "KES",
    "seller_phone": "+254712345678",
    "product_description": "iPhone 12 Pro Max",
    "payment_expiry": "2024-03-28T12:00:00"
  }
}
```

##### 2. Confirm Receipt (Release to Seller)
```
POST /escrow/confirm
```
Buyer confirms they received the item. Automatically releases funds to seller's M-Pesa.

**Request:**
```json
{
  "escrow_id": "507f1f77bcf86cd799439012",
  "buyer_phone": "0712345678"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "escrow_id": "507f1f77bcf86cd799439012",
    "amount": 1500.00,
    "seller_phone": "+254712345678",
    "transaction_id": "AT_TXN_123456",
    "message": "Funds successfully released to seller"
  }
}
```

##### 3. Get Escrow Status
```
GET /escrow/status/<escrow_id>?phone=0712345678
```
Check the current status of an escrow payment.

**Response:**
```json
{
  "success": true,
  "data": {
    "escrow_id": "507f1f77bcf86cd799439012",
    "status": "paid",
    "amount": 1500.00,
    "currency": "KES",
    "product_description": "iPhone 12 Pro Max",
    "buyer_phone": "+254712345678",
    "seller_phone": "+254723456789",
    "created_at": "2024-03-27T10:00:00",
    "paid_at": "2024-03-27T10:05:00",
    "confirmation_deadline": "2024-04-03T10:05:00",
    "history": [...]
  }
}
```

##### 4. Raise Dispute
```
POST /escrow/dispute
```
Buyer raises a dispute about the transaction.

**Request:**
```json
{
  "escrow_id": "507f1f77bcf86cd799439012",
  "buyer_phone": "0712345678",
  "reason": "Item not as described - wrong color"
}
```

##### 5. Process Refund (Admin)
```
POST /escrow/refund
```
Admin processes refund to buyer after dispute resolution.

**Request:**
```json
{
  "escrow_id": "507f1f77bcf86cd799439012",
  "admin_note": "Refund approved - seller did not deliver"
}
```

##### 6. Manual Release (Admin)
```
POST /escrow/release
```
Manually release funds to seller.

**Request:**
```json
{
  "escrow_id": "507f1f77bcf86cd799439012"
}
```

##### 7. Get Buyer's Escrows
```
GET /escrow/buyer/<phone>
```
Get all escrow payments for a specific buyer.

##### 8. Get Seller's Escrows
```
GET /escrow/seller/<phone>
```
Get all escrow payments for a specific seller.

##### 9. Process Auto-Releases (Cron)
```
POST /escrow/process-auto-releases
```
Automatically release escrows past their 7-day confirmation deadline.

##### 10. Process Expired Payments (Cron)
```
POST /escrow/process-expired
```
Cancel escrows where payment window (24 hours) has expired.

---

#### Social Media Upload API Endpoints

##### 1. Upload to TikTok
```
POST /upload/tiktok
```
Upload video or images to TikTok. Images are automatically converted to a slideshow video.

**Request:**
```json
{
  "media_urls": ["https://your-bucket.s3.amazonaws.com/video.mp4"],
  "is_video": true,
  "caption": "Check out this item! #ForSale #OwnAgain"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "video_url": "https://tiktok.com/@username/video/123456",
    "platform": "tiktok"
  }
}
```

**Notes:**
- For images, provide multiple URLs - they'll be converted to a slideshow video
- Videos should be MP4 format
- Caption supports hashtags

##### 2. Upload to Instagram
```
POST /upload/instagram
```
Upload to Instagram feed or stories.

**Request:**
```json
{
  "media_urls": ["https://bucket.s3.amazonaws.com/image1.jpg", "https://bucket.s3.amazonaws.com/image2.jpg"],
  "is_video": false,
  "caption": "New item for sale! #OwnAgain",
  "story": false
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "post_id": "17895695668004550",
    "platform": "instagram",
    "type": "feed"
  }
}
```

**Notes:**
- Set `story: true` to post as Instagram Story instead of feed
- Multiple images create a carousel post
- Single video creates a Reel

##### 3. Upload to Facebook
```
POST /upload/facebook
```
Upload to Facebook page.

**Request:**
```json
{
  "media_urls": ["https://bucket.s3.amazonaws.com/image.jpg"],
  "is_video": false,
  "caption": "Check out this listing!"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "post_url": "https://facebook.com/photo?fbid=123456",
    "platform": "facebook"
  }
}
```

##### 4. Upload to All Platforms
```
POST /upload/all
```
Upload media to multiple platforms at once.

**Request:**
```json
{
  "media_urls": ["https://bucket.s3.amazonaws.com/video.mp4"],
  "is_video": true,
  "caption": "Amazing item for sale!",
  "platforms": ["tiktok", "instagram", "facebook"]
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "tiktok": {
      "success": true,
      "video_url": "https://tiktok.com/..."
    },
    "instagram": {
      "success": true,
      "post_id": "17895695668004550"
    },
    "facebook": {
      "success": true,
      "post_url": "https://facebook.com/..."
    }
  }
}
```

**Notes:**
- `platforms` is optional - defaults to all three
- Each platform uploads independently - one failure doesn't affect others
- Returns individual success/error for each platform

---

### Environment Variables Required

#### Escrow Service
```env
# Pesapal (STK Push payments)
PESAPAL_CONSUMER_KEY=your_key
PESAPAL_CONSUMER_SECRET=your_secret
PESAPAL_IPN_ID=your_ipn_id
BASE_URL=https://your-domain.com

# Africa's Talking (B2C payouts)
AT_USERNAME=your_username
AT_API_KEY=your_api_key

# Twilio (WhatsApp notifications)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_NUMBER=+14155238886
```

#### TikTok Upload
```env
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_ACCESS_TOKEN=your_access_token
TIKTOK_REFRESH_TOKEN=your_refresh_token
```

#### Instagram/Facebook Upload
```env
INSTAGRAM_ACCOUNT_ID=your_account_id
INSTAGRAM_ACCESS_TOKEN=your_access_token
FACEBOOK_PAGE_ID=your_page_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_token
```

---

### Files Changed

| File | Changes |
|------|---------|
| `escrow_service.py` | **NEW** - Complete escrow payment service class |
| `app.py` | Added escrow endpoints, social media upload endpoints, imports |

---

### Payment Flow Diagram

```
1. BUYER INITIATES PURCHASE
   POST /escrow/pay
   └── Creates escrow record (status: pending)
   └── Initiates Pesapal STK Push
   └── Reserves product

2. BUYER COMPLETES PAYMENT
   Pesapal Callback → /pesapal-callback
   └── Updates escrow (status: paid)
   └── Sends WhatsApp to buyer & seller

3. ITEM DELIVERED

4. BUYER CONFIRMS RECEIPT
   POST /escrow/confirm
   └── Updates escrow (status: confirmed)
   └── Triggers B2C payout via Africa's Talking
   └── Updates escrow (status: released)
   └── Marks product as sold

   OR

4. BUYER RAISES DISPUTE
   POST /escrow/dispute
   └── Updates escrow (status: disputed)
   └── Admin reviews

5. ADMIN RESOLVES
   POST /escrow/refund  → Refund to buyer
   POST /escrow/release → Release to seller
```

---

### Cron Jobs (Recommended)

Set up the following cron jobs for automatic processing:

```bash
# Auto-release escrows past 7-day confirmation deadline (run daily)
0 0 * * * curl -X POST https://your-domain.com/escrow/process-auto-releases

# Cancel expired payment windows (run hourly)
0 * * * * curl -X POST https://your-domain.com/escrow/process-expired
```
