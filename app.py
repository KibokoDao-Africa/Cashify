from flask import Flask, request, current_app, jsonify
from flask_cors import CORS
from flasgger import Swagger
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from pymongo import MongoClient
import certifi
import os
import requests
import uuid
import boto3
import threading
from io import BytesIO
from datetime import datetime, timedelta
from payment import initiate_pesapal_payment, check_pesapal_payment_status
from facebook_graph_api import upload_to_facebook, upload_to_instagram
from tiktok_api import upload_to_tiktok
from bson import ObjectId
from template_manager import template_manager
from escrow_service import EscrowService

app = Flask(__name__)

# Configure CORS with specific settings
CORS(app, resources={
    r"/": {"origins": "*"},
    r"/products*": {"origins": "*"},
    r"/whatsapp": {"origins": "*"},
    r"/pesapal-callback": {"origins": "*"},
    r"/fees": {"origins": "*"},
    r"/upload/*": {"origins": "*"},
    r"/escrow/*": {"origins": "*"}
})

# Swagger configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "Cashify API",
        "description": "API for Cashify - A marketplace platform with escrow payments, product listings, and social media integration",
        "version": "1.0.0",
        "contact": {
            "name": "Cashify Support"
        }
    },
    "host": os.getenv("SWAGGER_HOST", "95.217.176.128:8000"),
    "basePath": "/",
    "schemes": ["http", "https"],
    "tags": [
        {"name": "Health", "description": "Health check endpoints"},
        {"name": "Products", "description": "Product management endpoints"},
        {"name": "Fees", "description": "Category fee management"},
        {"name": "Social Media", "description": "Social media upload endpoints"},
        {"name": "Escrow", "description": "Escrow payment endpoints"},
        {"name": "WhatsApp", "description": "WhatsApp webhook endpoint"},
        {"name": "Payment", "description": "Payment callback endpoints"}
    ]
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

# MongoDB connection with SSL configuration
mongo_client = MongoClient(
    os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
    tlsCAFile=certifi.where(),
    tls=True,
    tlsAllowInvalidCertificates=False,
    tlsAllowInvalidHostnames=False,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=10000
)
db = mongo_client[os.getenv("MONGODB_DATABASE", "cashify")]
sessions_collection = db.sessions
products_collection = db.products
fees_collection = db.fees  # Collection for category fees
pending_payments_collection = db.pending_payments
escrow_payments_collection = db.escrow_payments

# Initialize Escrow Service
escrow_service = EscrowService(db)

# AWS S3 Configuration
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

def initialize_default_fees():
    """
    Initialize default fees in MongoDB if they don't exist
    """
    if fees_collection.count_documents({}) == 0:
        default_fees = {
            "default": 400,
            "Real Estate": 1500,
            "Vehicles": 1500
        }
        fees_collection.insert_one(default_fees)
        current_app.logger.info("Initialized default category fees")

def get_fee_for_category(category):
    """
    Get the fee for a specific category.
    If no fee is set for that category, return the default fee.
    """
    fees = fees_collection.find_one()
    if not fees:
        initialize_default_fees()
        fees = fees_collection.find_one()
    
    # Return the category-specific fee if it exists, otherwise return default
    return 1    # TODO: Remove this line
    return fees.get(category, fees.get('default', 400))

def upload_to_s3(file_content, filename, content_type='image/jpeg'):
    """
    Upload a file to S3 bucket and return the public URL
    """
    try:
        # Upload the file to S3
        s3_client.upload_fileobj(
            BytesIO(file_content),
            S3_BUCKET,
            filename,
            ExtraArgs={
                'ContentType': content_type
            }
        )
        
        # Generate the URL for the uploaded file
        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"
        current_app.logger.info(f"File uploaded to S3: {s3_url}")
        return s3_url
    
    except Exception as e:
        current_app.logger.error(f"Error uploading to S3: {str(e)}")
        raise

def get_session(user_number):
    """
    Retrieves the session for the given user from MongoDB. 
    If none exists, create a new session with a default 'INIT' state.
    """
    session_doc = sessions_collection.find_one({"user_number": user_number})
    if session_doc is None:
        session = {"user_number": user_number, "state": "INIT"}
        sessions_collection.insert_one(session)
        # Remove MongoDB's _id from the returned session
        session.pop("_id", None)
        return session
    else:
        # Remove MongoDB's _id from the returned session
        session_doc.pop("_id", None)
        return session_doc

def set_session(user_number, session):
    """
    Stores/updates the session for the given user in MongoDB.
    """
    session["user_number"] = user_number
    sessions_collection.update_one(
        {"user_number": user_number},
        {"$set": session},
        upsert=True
    )

def reset_session(user_number):
    """
    Resets the session for the given user in MongoDB.
    """
    sessions_collection.delete_one({"user_number": user_number})

def get_user_products(user_number, min_age_days=0):
    """
    Get all active products for a given user
    If min_age_days is specified, only return products older than that many days
    """
    query = {
        "user_number": user_number,
        "status": "active",
        "sold": False
    }
    
    # Add date filter if min_age_days is specified
    if min_age_days > 0:
        cutoff_date = datetime.utcnow() - timedelta(days=min_age_days)
        query["created_at"] = {"$lte": cutoff_date}
    
    products = products_collection.find(query).sort("created_at", -1)
    
    result = []
    for product in products:
        result.append({
            "id": str(product["_id"]),
            "description": product.get("description", ""),
            "selling_price": product.get("selling_price", "")
        })
    
    return result

def mark_product_as_sold(product_id):
    """
    Mark a product as sold in the database
    """
    result = products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"sold": True}}
    )
    
    return result.modified_count > 0

def save_product(user_number, media_urls, media_type, description, category, condition, buying_price, 
                selling_price, reason_for_selling, location, contact):
    """
    Save a product to the database with all details
    """
    product = {
        "user_number": user_number,
        "media_urls": media_urls,  # List of URLs
        "media_type": media_type,  # "images" or "video"
        "description": description,
        "category": category,
        "condition": condition,
        "buying_price": buying_price,
        "selling_price": selling_price,
        "reason_for_selling": reason_for_selling,
        "location": location,
        "contact": contact,
        "created_at": datetime.utcnow(),
        "status": "active",
        "sold": False
    }
    
    result = products_collection.insert_one(product)
    current_app.logger.info(f"Product saved with ID: {result.inserted_id}")
    return str(result.inserted_id)

def process_social_media_uploads(user_number, media_urls, media_type, description, category, condition, selling_price, location, contact):
    """
    Process social media uploads in a background thread and send a follow-up message when complete
    """
    try:
        # Create a list to track where posting succeeded
        posting_results = []
        
        # Prepare detailed captions for different platforms
        base_caption = f"FOR SALE: {description}\n\n"
        base_caption += f"📋 Category: {category}\n"
        base_caption += f"🔍 Condition: {condition}\n"
        base_caption += f"💰 Price: {selling_price}\n"
        base_caption += f"📍 Location: {location}\n"
        base_caption += f"📞 Contact: {contact}\n\n"
        
        insta_caption = base_caption + "Contact us to purchase this item! #OwnAgain #ForSale"
        story_caption = f"NEW ITEM: {description} - {selling_price}"
        fb_caption = "🔥 NEW LISTING 🔥\n\n" + base_caption + "Interested? Contact us through WhatsApp! #OwnAgain #MarketplaceAlternative"
        
        is_video = media_type == "video"
        
        # Try posting to each platform
        try:
            link = upload_to_facebook(media_urls=media_urls, is_video=is_video, caption=fb_caption)
            posting_results.append("Facebook post created with link: " + link)
        except Exception as e:
            posting_results.append(f"Error posting to Facebook: {str(e)}")

        try:
            upload_to_instagram(media_urls=media_urls, is_video=is_video, caption=insta_caption)
            posting_results.append(f"Instagram post created, visit https://www.instagram.com/own_again/ to view")
        except Exception as e:
            posting_results.append(f"Error posting to Instagram: {str(e)}")
            
        try:
            upload_to_instagram(media_urls=media_urls, is_video=is_video, caption=story_caption, story=True)
            posting_results.append(f"Instagram story(ies) created, visit https://www.instagram.com/stories/own_again/ to view")
        except Exception as e:
            posting_results.append(f"Error posting to Instagram stories: {str(e)}")

        # Send follow-up message with results
        follow_up_message = "✅ Social Media Upload Results:\n\n"
        follow_up_message += "\n".join(posting_results)
        follow_up_message += "\n\nThank you for using Own Again!"
        
        # Send the follow-up message using Twilio
        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        twilio_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
        if not twilio_number.startswith('whatsapp:'):
            twilio_number = f"whatsapp:{twilio_number}"
            
        client.messages.create(
            body=follow_up_message,
            from_=twilio_number,
            to=user_number
        )
        
    except Exception as e:
        # Log any errors
        print(f"Error in background processing: {str(e)}")

@app.route("/products", methods=["POST"])
def create_product():
    """Create a new product listing
    ---
    tags:
      - Products
    summary: Create a new product
    description: Creates a new product listing with all required details
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - user_number
            - media_urls
            - media_type
            - description
            - category
            - condition
            - buying_price
            - selling_price
            - reason_for_selling
            - location
            - contact
          properties:
            user_number:
              type: string
              example: "+254712345678"
            media_urls:
              type: array
              items:
                type: string
              example: ["https://example.com/image1.jpg", "https://example.com/image2.jpg"]
            media_type:
              type: string
              enum: [images, video]
              example: images
            description:
              type: string
              example: "iPhone 15 Pro Max in excellent condition"
            category:
              type: string
              example: "Electronics"
            condition:
              type: string
              example: "Used - Like New"
            buying_price:
              type: number
              example: 120000
            selling_price:
              type: number
              example: 100000
            reason_for_selling:
              type: string
              example: "Upgrading to newer model"
            location:
              type: string
              example: "Nairobi, Kenya"
            contact:
              type: string
              example: "+254712345678"
    responses:
      201:
        description: Product created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                id:
                  type: string
                  example: "507f1f77bcf86cd799439011"
                message:
                  type: string
                  example: "Product created successfully"
      400:
        description: Missing required field
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Missing required field: description"
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Failed to create product"
    """
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ["user_number", "media_urls", "media_type", "description", "category", 
                           "condition", "buying_price", "selling_price", 
                           "reason_for_selling", "location", "contact"]
        
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "success": False,
                    "error": f"Missing required field: {field}"
                }), 400
        
        # Save the product to the database
        product_id = save_product(
            user_number=data["user_number"],
            media_urls=data["media_urls"],
            media_type=data["media_type"],
            description=data["description"],
            category=data["category"],
            condition=data["condition"],
            buying_price=data["buying_price"],
            selling_price=data["selling_price"],
            reason_for_selling=data["reason_for_selling"],
            location=data["location"],
            contact=data["contact"]
        )
        
        return jsonify({
            "success": True,
            "data": {
                "id": product_id,
                "message": "Product created successfully"
            }
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Error creating product: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to create product"
        }), 500

@app.route("/products", methods=["GET"])
def get_all_products():
    """Get all products
    ---
    tags:
      - Products
    summary: Get all active products
    description: Retrieves all active and unsold products with pagination support
    parameters:
      - in: query
        name: page
        type: integer
        default: 1
        description: Page number for pagination
      - in: query
        name: limit
        type: integer
        default: 20
        description: Number of products per page
    responses:
      200:
        description: Products retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: string
                    example: "507f1f77bcf86cd799439011"
                  description:
                    type: string
                    example: "iPhone 15 Pro Max"
                  media_urls:
                    type: array
                    items:
                      type: string
                    example: ["https://example.com/image1.jpg"]
                  media_type:
                    type: string
                    example: "images"
                  category:
                    type: string
                    example: "Electronics"
                  condition:
                    type: string
                    example: "Used - Like New"
                  buying_price:
                    type: number
                    example: 120000
                  selling_price:
                    type: number
                    example: 100000
                  reason_for_selling:
                    type: string
                    example: "Upgrading"
                  location:
                    type: string
                    example: "Nairobi"
                  contact:
                    type: string
                    example: "+254712345678"
                  created_at:
                    type: string
                    format: date-time
                  user_number:
                    type: string
                    example: "+254712345678"
            pagination:
              type: object
              properties:
                current_page:
                  type: integer
                  example: 1
                limit:
                  type: integer
                  example: 20
                total_products:
                  type: integer
                  example: 100
                total_pages:
                  type: integer
                  example: 5
      500:
        description: Server error
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Failed to fetch products"
    """
    try:
        # Get query parameters for pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Query products sorted by creation date (newest first)
        # Only return active and unsold products
        products_cursor = products_collection.find(
            {"status": "active", "sold": False}
        ).sort("created_at", -1).skip(skip).limit(limit)
        
        products = []
        for product in products_cursor:
            # Convert ObjectId to string and format the product
            product_data = {
                "id": str(product["_id"]),
                "description": product["description"],
                "media_urls": product.get("media_urls", []),
                "media_type": product.get("media_type", "images"),
                "category": product.get("category", ""),
                "condition": product.get("condition", ""),
                "buying_price": product.get("buying_price", ""),
                "selling_price": product.get("selling_price", ""),
                "reason_for_selling": product.get("reason_for_selling", ""),
                "location": product.get("location", ""),
                "contact": product.get("contact", ""),
                "created_at": product["created_at"].isoformat() if product.get("created_at") else None,
                "user_number": product.get("user_number", "Anonymous")
            }
            products.append(product_data)
        
        # Get total count for pagination info
        total_products = products_collection.count_documents({"status": "active", "sold": False})
        
        return jsonify({
            "success": True,
            "data": products,
            "pagination": {
                "current_page": page,
                "limit": limit,
                "total_products": total_products,
                "total_pages": (total_products + limit - 1) // limit
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error fetching products: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to fetch products"
        }), 500

@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    """Get a specific product
    ---
    tags:
      - Products
    summary: Get product by ID
    description: Retrieves details of a specific product by its ID
    parameters:
      - in: path
        name: product_id
        type: string
        required: true
        description: The product ID (MongoDB ObjectId)
        example: "507f1f77bcf86cd799439011"
    responses:
      200:
        description: Product found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                id:
                  type: string
                description:
                  type: string
                media_urls:
                  type: array
                  items:
                    type: string
                media_type:
                  type: string
                category:
                  type: string
                condition:
                  type: string
                buying_price:
                  type: number
                selling_price:
                  type: number
                reason_for_selling:
                  type: string
                location:
                  type: string
                contact:
                  type: string
                created_at:
                  type: string
                  format: date-time
                user_number:
                  type: string
                sold:
                  type: boolean
      404:
        description: Product not found
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Product not found"
      500:
        description: Server error
    """
    try:
        product = products_collection.find_one({"_id": ObjectId(product_id)})
        
        if not product:
            return jsonify({
                "success": False,
                "error": "Product not found"
            }), 404
        
        product_data = {
            "id": str(product["_id"]),
            "description": product["description"],
            "media_urls": product.get("media_urls", []),
            "media_type": product.get("media_type", "images"),
            "category": product.get("category", ""),
            "condition": product.get("condition", ""),
            "buying_price": product.get("buying_price", ""),
            "selling_price": product.get("selling_price", ""),
            "reason_for_selling": product.get("reason_for_selling", ""),
            "location": product.get("location", ""),
            "contact": product.get("contact", ""),
            "created_at": product["created_at"].isoformat() if product.get("created_at") else None,
            "user_number": product.get("user_number", "Anonymous"),
            "sold": product.get("sold", False)
        }
        
        return jsonify({
            "success": True,
            "data": product_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error fetching product {product_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to fetch product"
        }), 500

@app.route("/fees", methods=["GET", "POST"])
def manage_fees():
    """Manage category fees
    ---
    tags:
      - Fees
    summary: Get or update category fees
    description: Retrieve current fee structure or update fees for specific categories
    parameters:
      - in: body
        name: body
        required: false
        description: Only required for POST requests to update fees
        schema:
          type: object
          properties:
            category:
              type: string
              example: "Electronics"
            fee_percentage:
              type: number
              example: 5
    responses:
      200:
        description: Fees retrieved or updated successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              example: {"default": 400, "Real Estate": 1500, "Vehicles": 1500}
            message:
              type: string
              example: "Fees updated successfully"
      400:
        description: Invalid data format
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "Invalid data format"
      500:
        description: Server error
    """
    try:
        # Initialize fees if they don't exist
        initialize_default_fees()
        
        if request.method == "GET":
            # Return the current fee structure
            fees = fees_collection.find_one({}, {"_id": 0})  # Exclude _id field
            return jsonify({
                "success": True,
                "data": fees
            })
            
        elif request.method == "POST":
            # Update fees
            data = request.json
            
            if not data or not isinstance(data, dict):
                return jsonify({
                    "success": False,
                    "error": "Invalid data format. Expected dictionary of category names and fees."
                }), 400
            
            # Get current fees and update with new values
            current_fees = fees_collection.find_one({})
            
            # Delete _id from current fees for easy update
            if current_fees and "_id" in current_fees:
                current_fees_id = current_fees["_id"]
                del current_fees["_id"]
            else:
                # If no fees exist, create new document
                current_fees = {"default": 400}
                result = fees_collection.insert_one(current_fees)
                current_fees_id = result.inserted_id
            
            # Update with new fees
            current_fees.update(data)
            
            # Save updated fees
            fees_collection.update_one(
                {"_id": current_fees_id},
                {"$set": current_fees}
            )
            
            return jsonify({
                "success": True,
                "message": "Fees updated successfully",
                "data": current_fees
            })
            
    except Exception as e:
        current_app.logger.error(f"Error managing fees: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to manage fees"
        }), 500


# =============================================================================
# SOCIAL MEDIA UPLOAD API ENDPOINTS
# =============================================================================

@app.route("/upload/tiktok", methods=["POST"])
def upload_tiktok_media():
    """Upload media to TikTok
    ---
    tags:
      - Social Media
    summary: Upload video or images to TikTok
    description: Upload media to TikTok. Images are automatically converted to a slideshow video
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - media_urls
          properties:
            media_urls:
              type: array
              items:
                type: string
              example: ["https://example.com/video.mp4"]
            is_video:
              type: boolean
              default: false
              example: true
            caption:
              type: string
              example: "Check out this item! #ForSale"
    responses:
      200:
        description: Upload successful
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                video_url:
                  type: string
                  example: "https://tiktok.com/..."
                platform:
                  type: string
                  example: "tiktok"
      400:
        description: Missing required field
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: "media_urls is required"
      500:
        description: Upload failed
    """
    try:
        data = request.json

        # Validate required fields
        if "media_urls" not in data or not data["media_urls"]:
            return jsonify({"success": False, "error": "media_urls is required"}), 400

        media_urls = data["media_urls"]
        is_video = data.get("is_video", False)
        caption = data.get("caption", "")

        # Upload to TikTok
        result = upload_to_tiktok(
            media_urls=media_urls,
            is_video=is_video,
            caption=caption
        )

        return jsonify({
            "success": True,
            "data": {
                "video_url": result,
                "platform": "tiktok"
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error uploading to TikTok: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"TikTok upload failed: {str(e)}"
        }), 500


@app.route("/upload/instagram", methods=["POST"])
def upload_instagram_media():
    """Upload media to Instagram
    ---
    tags:
      - Social Media
    summary: Upload video or images to Instagram
    description: Upload media to Instagram feed or story
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - media_urls
          properties:
            media_urls:
              type: array
              items:
                type: string
              example: ["https://example.com/image1.jpg", "https://example.com/image2.jpg"]
            is_video:
              type: boolean
              default: false
            caption:
              type: string
              example: "Check out this item!"
            story:
              type: boolean
              default: false
              description: Set to true to post as story instead of feed
    responses:
      200:
        description: Upload successful
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                post_id:
                  type: string
                  example: "17895695668004550"
                platform:
                  type: string
                  example: "instagram"
                type:
                  type: string
                  enum: [feed, story]
      400:
        description: Missing required field
      500:
        description: Upload failed
    """
    try:
        data = request.json

        if "media_urls" not in data or not data["media_urls"]:
            return jsonify({"success": False, "error": "media_urls is required"}), 400

        media_urls = data["media_urls"]
        is_video = data.get("is_video", False)
        caption = data.get("caption", "")
        story = data.get("story", False)

        result = upload_to_instagram(
            media_urls=media_urls,
            is_video=is_video,
            caption=caption,
            story=story
        )

        return jsonify({
            "success": True,
            "data": {
                "post_id": result,
                "platform": "instagram",
                "type": "story" if story else "feed"
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error uploading to Instagram: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Instagram upload failed: {str(e)}"
        }), 500


@app.route("/upload/facebook", methods=["POST"])
def upload_facebook_media():
    """Upload media to Facebook
    ---
    tags:
      - Social Media
    summary: Upload video or images to Facebook
    description: Upload media to Facebook page
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - media_urls
          properties:
            media_urls:
              type: array
              items:
                type: string
              example: ["https://example.com/image1.jpg"]
            is_video:
              type: boolean
              default: false
            caption:
              type: string
              example: "Check out this item!"
    responses:
      200:
        description: Upload successful
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                post_url:
                  type: string
                  example: "https://facebook.com/..."
                platform:
                  type: string
                  example: "facebook"
      400:
        description: Missing required field
      500:
        description: Upload failed
    """
    try:
        data = request.json

        if "media_urls" not in data or not data["media_urls"]:
            return jsonify({"success": False, "error": "media_urls is required"}), 400

        media_urls = data["media_urls"]
        is_video = data.get("is_video", False)
        caption = data.get("caption", "")

        result = upload_to_facebook(
            media_urls=media_urls,
            is_video=is_video,
            caption=caption
        )

        return jsonify({
            "success": True,
            "data": {
                "post_url": result,
                "platform": "facebook"
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error uploading to Facebook: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Facebook upload failed: {str(e)}"
        }), 500


@app.route("/upload/all", methods=["POST"])
def upload_to_all_platforms():
    """Upload media to all platforms
    ---
    tags:
      - Social Media
    summary: Upload to all social media platforms
    description: Upload media to TikTok, Instagram, and Facebook simultaneously
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - media_urls
          properties:
            media_urls:
              type: array
              items:
                type: string
              example: ["https://example.com/image1.jpg"]
            is_video:
              type: boolean
              default: false
            caption:
              type: string
              example: "Check out this item!"
            platforms:
              type: array
              items:
                type: string
                enum: [tiktok, instagram, facebook]
              default: ["tiktok", "instagram", "facebook"]
              description: Platforms to upload to (defaults to all)
    responses:
      200:
        description: Upload completed (check individual platform results)
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                tiktok:
                  type: object
                  properties:
                    success:
                      type: boolean
                    video_url:
                      type: string
                instagram:
                  type: object
                  properties:
                    success:
                      type: boolean
                    post_id:
                      type: string
                facebook:
                  type: object
                  properties:
                    success:
                      type: boolean
                    post_url:
                      type: string
      400:
        description: Missing required field
      500:
        description: Upload failed
    """
    try:
        data = request.json

        if "media_urls" not in data or not data["media_urls"]:
            return jsonify({"success": False, "error": "media_urls is required"}), 400

        media_urls = data["media_urls"]
        is_video = data.get("is_video", False)
        caption = data.get("caption", "")
        platforms = data.get("platforms", ["tiktok", "instagram", "facebook"])

        results = {}

        # Upload to TikTok
        if "tiktok" in platforms:
            try:
                tiktok_result = upload_to_tiktok(
                    media_urls=media_urls,
                    is_video=is_video,
                    caption=caption
                )
                results["tiktok"] = {"success": True, "video_url": tiktok_result}
            except Exception as e:
                results["tiktok"] = {"success": False, "error": str(e)}

        # Upload to Instagram
        if "instagram" in platforms:
            try:
                instagram_result = upload_to_instagram(
                    media_urls=media_urls,
                    is_video=is_video,
                    caption=caption
                )
                results["instagram"] = {"success": True, "post_id": instagram_result}
            except Exception as e:
                results["instagram"] = {"success": False, "error": str(e)}

        # Upload to Facebook
        if "facebook" in platforms:
            try:
                facebook_result = upload_to_facebook(
                    media_urls=media_urls,
                    is_video=is_video,
                    caption=caption
                )
                results["facebook"] = {"success": True, "post_url": facebook_result}
            except Exception as e:
                results["facebook"] = {"success": False, "error": str(e)}

        # Check if any platform succeeded
        any_success = any(r.get("success") for r in results.values())

        return jsonify({
            "success": any_success,
            "data": results
        })

    except Exception as e:
        current_app.logger.error(f"Error uploading to platforms: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Upload failed: {str(e)}"
        }), 500


# =============================================================================
# ESCROW API ENDPOINTS
# =============================================================================

@app.route("/escrow/pay", methods=["POST"])
def create_escrow_payment():
    """Create escrow payment
    ---
    tags:
      - Escrow
    summary: Create an escrow payment for a product
    description: Buyer initiates payment for a product. Money is held in escrow until buyer confirms receipt
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - product_id
            - buyer_phone
          properties:
            product_id:
              type: string
              example: "507f1f77bcf86cd799439011"
              description: MongoDB ObjectId of the product
            buyer_phone:
              type: string
              example: "254712345678"
              description: Buyer's phone number
            buyer_name:
              type: string
              example: "John Doe"
              description: Buyer's name (optional)
    responses:
      201:
        description: Escrow payment created successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                escrow_id:
                  type: string
                  example: "507f1f77bcf86cd799439012"
                payment_url:
                  type: string
                  example: "https://pay.pesapal.com/..."
                amount:
                  type: number
                  example: 1500.00
                currency:
                  type: string
                  example: "KES"
                seller_phone:
                  type: string
                  example: "+254712345678"
                product_description:
                  type: string
                  example: "iPhone 15 Pro Max"
                payment_expiry:
                  type: string
                  format: date-time
      400:
        description: Missing required field or invalid request
      500:
        description: Failed to create escrow payment
    """
    try:
        data = request.json

        # Validate required fields
        required_fields = ["product_id", "buyer_phone"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

        result = escrow_service.create_escrow_payment(
            product_id=data["product_id"],
            buyer_phone=data["buyer_phone"],
            buyer_name=data.get("buyer_name")
        )

        if result.get("success"):
            return jsonify(result), 201
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error creating escrow payment: {str(e)}")
        return jsonify({"success": False, "error": "Failed to create escrow payment"}), 500


@app.route("/escrow/confirm", methods=["POST"])
def confirm_escrow_receipt():
    """Confirm receipt of goods
    ---
    tags:
      - Escrow
    summary: Buyer confirms receipt of item
    description: Buyer confirms they received the item, triggering automatic release of funds to seller
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - escrow_id
            - buyer_phone
          properties:
            escrow_id:
              type: string
              example: "507f1f77bcf86cd799439012"
              description: The escrow payment ID
            buyer_phone:
              type: string
              example: "254712345678"
              description: Buyer's phone number for verification
    responses:
      200:
        description: Funds released successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                escrow_id:
                  type: string
                amount:
                  type: number
                  example: 1500.00
                seller_phone:
                  type: string
                  example: "+254712345678"
                transaction_id:
                  type: string
                  example: "AT_TXN_123"
                message:
                  type: string
                  example: "Funds successfully released to seller"
      400:
        description: Missing required field or invalid request
      500:
        description: Failed to confirm receipt
    """
    try:
        data = request.json

        required_fields = ["escrow_id", "buyer_phone"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

        result = escrow_service.confirm_receipt(
            escrow_id=data["escrow_id"],
            buyer_phone=data["buyer_phone"]
        )

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error confirming escrow receipt: {str(e)}")
        return jsonify({"success": False, "error": "Failed to confirm receipt"}), 500


@app.route("/escrow/release", methods=["POST"])
def release_escrow_payment():
    """
    Endpoint to manually release funds to a seller.
    Used by admin or automated processes.

    Request body:
    {
        "escrow_id": "escrow_object_id"
    }
    """
    try:
        data = request.json

        if "escrow_id" not in data:
            return jsonify({"success": False, "error": "Missing escrow_id"}), 400

        result = escrow_service.release_funds(escrow_id=data["escrow_id"])

        if result.get("success"):
            current_app.logger.info(f"Escrow funds released: {result}")
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error releasing escrow payment: {str(e)}")
        return jsonify({"success": False, "error": "Failed to release escrow payment"}), 500


@app.route("/escrow/status/<escrow_id>", methods=["GET"])
def get_escrow_status(escrow_id):
    """Get escrow payment status
    ---
    tags:
      - Escrow
    summary: Get escrow payment status
    description: Retrieve the current status and details of an escrow payment
    parameters:
      - in: path
        name: escrow_id
        type: string
        required: true
        description: The escrow payment ID
        example: "507f1f77bcf86cd799439012"
      - in: query
        name: phone
        type: string
        required: false
        description: Phone number for verification (optional)
        example: "254712345678"
    responses:
      200:
        description: Escrow status retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                escrow_id:
                  type: string
                status:
                  type: string
                  enum: [pending, paid, confirmed, released, disputed, refunded, cancelled, expired]
                  example: "paid"
                amount:
                  type: number
                  example: 1500.00
                currency:
                  type: string
                  example: "KES"
                product_description:
                  type: string
                buyer_phone:
                  type: string
                seller_phone:
                  type: string
                created_at:
                  type: string
                  format: date-time
                paid_at:
                  type: string
                  format: date-time
                confirmation_deadline:
                  type: string
                  format: date-time
                history:
                  type: array
                  items:
                    type: object
      404:
        description: Escrow payment not found
      500:
        description: Failed to get escrow status
    """
    try:
        requester_phone = request.args.get("phone")
        result = escrow_service.get_escrow_status(
            escrow_id=escrow_id,
            requester_phone=requester_phone
        )

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 404

    except Exception as e:
        current_app.logger.error(f"Error getting escrow status: {str(e)}")
        return jsonify({"success": False, "error": "Failed to get escrow status"}), 500


@app.route("/escrow/dispute", methods=["POST"])
def raise_escrow_dispute():
    """Raise escrow dispute
    ---
    tags:
      - Escrow
    summary: Raise a dispute on an escrow payment
    description: Buyer can raise a dispute if item is not as described or not received
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - escrow_id
            - buyer_phone
            - reason
          properties:
            escrow_id:
              type: string
              example: "507f1f77bcf86cd799439012"
            buyer_phone:
              type: string
              example: "254712345678"
            reason:
              type: string
              example: "Item not as described"
    responses:
      200:
        description: Dispute raised successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
      400:
        description: Missing required field or invalid request
      500:
        description: Failed to raise dispute
    """
    try:
        data = request.json

        required_fields = ["escrow_id", "buyer_phone", "reason"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

        result = escrow_service.raise_dispute(
            escrow_id=data["escrow_id"],
            buyer_phone=data["buyer_phone"],
            reason=data["reason"]
        )

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error raising dispute: {str(e)}")
        return jsonify({"success": False, "error": "Failed to raise dispute"}), 500


@app.route("/escrow/refund", methods=["POST"])
def process_escrow_refund():
    """
    Admin endpoint to process a refund to buyer.

    Request body:
    {
        "escrow_id": "escrow_object_id",
        "admin_note": "Refund approved due to..."
    }
    """
    try:
        data = request.json

        if "escrow_id" not in data:
            return jsonify({"success": False, "error": "Missing escrow_id"}), 400

        result = escrow_service.process_refund(
            escrow_id=data["escrow_id"],
            admin_note=data.get("admin_note")
        )

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error processing refund: {str(e)}")
        return jsonify({"success": False, "error": "Failed to process refund"}), 500


@app.route("/escrow/buyer/<buyer_phone>", methods=["GET"])
def get_buyer_escrows(buyer_phone):
    """
    Get all escrow payments for a buyer.

    Response:
    {
        "success": true,
        "data": [
            {
                "escrow_id": "...",
                "status": "paid",
                "amount": 1500.00,
                "product_description": "...",
                "created_at": "..."
            },
            ...
        ]
    }
    """
    try:
        result = escrow_service.get_buyer_escrows(buyer_phone=buyer_phone)

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error getting buyer escrows: {str(e)}")
        return jsonify({"success": False, "error": "Failed to get buyer escrows"}), 500


@app.route("/escrow/seller/<seller_phone>", methods=["GET"])
def get_seller_escrows(seller_phone):
    """
    Get all escrow payments for a seller.

    Response:
    {
        "success": true,
        "data": [
            {
                "escrow_id": "...",
                "status": "paid",
                "amount": 1500.00,
                "product_description": "...",
                "buyer_phone": "+254...",
                "created_at": "..."
            },
            ...
        ]
    }
    """
    try:
        result = escrow_service.get_seller_escrows(seller_phone=seller_phone)

        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        current_app.logger.error(f"Error getting seller escrows: {str(e)}")
        return jsonify({"success": False, "error": "Failed to get seller escrows"}), 500


@app.route("/escrow/process-auto-releases", methods=["POST"])
def process_auto_releases():
    """
    Admin/Cron endpoint to process automatic releases for escrows
    that have passed their confirmation deadline.
    """
    try:
        result = escrow_service.process_auto_releases()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error processing auto releases: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/escrow/process-expired", methods=["POST"])
def process_expired_payments():
    """
    Admin/Cron endpoint to cancel escrows with expired payment windows.
    """
    try:
        result = escrow_service.process_expired_payments()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error processing expired payments: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    current_app.logger.info("------------------------------Webhook Received------------------------------")

    # Parse the incoming message information from Twilio's POST data
    from_number = request.form.get("From")
    incoming_text = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", "0"))
    profile_name = request.form.get("ProfileName", "")  # Get profile name from webhook
    
    # Check for interactive message response
    button_payload = request.form.get("ButtonPayload")
    list_reply_id = request.form.get("ListId")
    
    # Create response object
    response = MessagingResponse()

    # ---------------------------------------------------------------------
    # Reset Conversation
    # ---------------------------------------------------------------------

    if incoming_text.upper() == "RESET":
        reset_session(from_number)
        response.message(f"Welcome back to Own Again, {profile_name}! Please send at least 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
        return str(response)

    # ---------------------------------------------------------------------
    # Conversation Flow
    # ---------------------------------------------------------------------

    state = get_session(from_number).get("state", "INIT")
    current_app.logger.info(f"User {from_number} in state '{state}' sent message: {incoming_text}")

    if state == "INIT":
        # User has sent media
        if num_media > 0:
            content_type = request.form.get("MediaContentType0", "")
            is_video = content_type.startswith("video/")
            is_image = content_type.startswith("image/")
                
            if is_video:
                # Process the video
                    twilio_media_url = request.form.get("MediaUrl0")
                    
                    # Download and upload to S3
                    auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                    media_response = requests.get(twilio_media_url, auth=auth)
                    
                    if media_response.status_code != 200:
                        response.message("Sorry, I couldn't download your video. Please try again.")
                        return str(response)
                    
                    filename = f"own_again_feed_{uuid.uuid4()}.mp4"
                    public_media_url = upload_to_s3(
                        media_response.content, 
                        filename, 
                        content_type=content_type
                    )
                    
                    # Store video (Overwrite existing media because only 1 video allowed)
                    session = get_session(from_number)
                    session["media_urls"] = [public_media_url]
                    session["media_type"] = "video"
                    set_session(from_number, session)
                    
                    response.message("Great! I received your video. Please enter a description for your item.")
            
            elif is_image:
                try:
                    # Process the new image
                    twilio_media_url = request.form.get("MediaUrl0")
                    
                    # Download and upload to S3
                    auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                    media_response = requests.get(twilio_media_url, auth=auth)
                    
                    if media_response.status_code != 200:
                        response.message("Sorry, I couldn't download your image. Please try again.")
                        return str(response)
                    
                    filename = f"own_again_feed_{uuid.uuid4()}.jpg"
                    public_media_url = upload_to_s3(
                        media_response.content, 
                        filename, 
                        content_type=content_type
                    )
                    
                    # Save the image in the user session
                    session = get_session(from_number)

                    current_app.logger.info(f"Current session before adding image: {session}. Media url: {public_media_url}")

                    media_urls = session.get("media_urls", [])
                    media_type = session.get("media_type", "images")

                    if media_type == "video":
                        # Previously a video was sent but now it's an image. Which means we start over
                        media_urls = [public_media_url]
                    else:
                        # Append the image to the previously sent images
                        media_urls.append(public_media_url)

                    session["media_urls"] = media_urls
                    session["media_type"] = "images"
                    set_session(from_number, session)

                    if len(media_urls) < 3:
                        response.message(f"Image {len(media_urls)}/3+ processed successfully")
                    else:
                        response.message(f"Image {len(media_urls)}/3+ processed successfully. You may now upload more images or enter a description of your item.")

                except Exception as e:
                    current_app.logger.error(f"Error processing image: {str(e)}")
                    response.message("Sorry, I couldn't process your image. Please try again.")
        
            else:
                response.message("Please send only images or a video.")
                return str(response)
        
        # User has sent text
        else:
            current_count = len(get_session(from_number).get("media_urls", []))
            needed = 3 - current_count

            if current_count == 0:
                # If the user wants to mark a product as sold:
                if incoming_text and incoming_text.upper() == "SOLD":
                    products = get_user_products(from_number, min_age_days=7)
                    if not products:
                        response.message("You don't have any products that are at least 7 days old available to mark as sold.")
                        return str(response)
                    
                    # Create interactive list for product selection
                    list_items = []
                    for i, product in enumerate(products):
                        list_items.append({
                            "id": f"product_{i}",
                            "title": f"{product['description'][:20]}... - ${product['selling_price']}"
                        })
                    
                    content_sid = template_manager.get_or_create_list_template(
                        template_name="product_selection_list",
                        body="Choose which product you want to mark as sold:",
                        items=list_items
                    )
                    
                    if content_sid:
                        # Store products in session for reference
                        session = get_session(from_number)
                        session["products"] = products
                        session["state"] = "AWAITING_PRODUCT_SELECTION"
                        set_session(from_number, session)
                        
                        template_manager.send_interactive_message(from_number, content_sid)
                    else:
                        # Fallback to text message
                        product_list = "Your products (7+ days old) available to mark as sold:\n\n"
                        for i, product in enumerate(products):
                            product_list += f"{i+1}. {product['description']} - ${product['selling_price']}\n"
                        product_list += "\nReply with the number of the product you want to mark as sold:"
                        response.message(product_list)
                else:
                    # Send a welcome message with user's name
                    response.message(f"Hi {profile_name}! Please send at least 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
            elif current_count < 3 and get_session(from_number).get("media_type") == "images":
                # Remind user to add more images
                response.message(f"Please send {3 - current_count} more image{'s' if needed > 1 else ''} to meet the minimum requirement, or type RESET to start over.")
            else:
                # Save incoming text as description and show category selection
                if incoming_text:
                    session = get_session(from_number)
                    session["description"] = incoming_text
                    session["state"] = "AWAITING_CATEGORY"
                    set_session(from_number, session)
                    
                    # Create interactive list for categories
                    categories = ["Electronics", "Clothing", "Furniture", "Vehicles", 
                                "Home Appliances", "Real Estate", "Services", "Other"]
                    
                    category_items = []
                    for cat in categories:
                        category_items.append({
                            "id": f"cat_{cat.lower().replace(' ', '_')}",
                            "title": cat
                        })
                    
                    content_sid = template_manager.get_or_create_list_template(
                        template_name="category_selection_list",
                        body="Please select a category for your item:",
                        items=category_items
                    )
                    
                    if content_sid:
                        template_manager.send_interactive_message(from_number, content_sid)
                    else:
                        # Fallback to text message
                        category_message = "Please select a category for your item by typing the number:\n\n" + \
                                        "\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categories)])
                        response.message(category_message)
                else:
                    response.message("I didn't catch that. Please send more images, or a text description for your item.")

    elif state == "AWAITING_PRODUCT_SELECTION":
        if list_reply_id:
            # Handle interactive list response
            try:
                product_index = int(list_reply_id.split("_")[1])
                products = get_session(from_number).get("products", [])
                
                if 0 <= product_index < len(products):
                    selected_product = products[product_index]
                    product_id = selected_product["id"]
                    
                    success = mark_product_as_sold(product_id)
                    
                    if success:
                        response.message(f"✅ Your product \"{selected_product['description']}\" has been marked as sold!")
                    else:
                        response.message("❌ Sorry, we couldn't mark the product as sold. Please try again.")
                    
                    reset_session(from_number)
                else:
                    response.message("Invalid selection. Please try again.")
            except (ValueError, IndexError):
                response.message("Invalid selection. Please try again.")
        else:
            # Fallback for text input
            try:
                selection = int(incoming_text)
                products = get_session(from_number).get("products", [])
                
                if 1 <= selection <= len(products):
                    selected_product = products[selection - 1]
                    product_id = selected_product["id"]
                    
                    success = mark_product_as_sold(product_id)
                    
                    if success:
                        response.message(f"✅ Your product \"{selected_product['description']}\" has been marked as sold!")
                    else:
                        response.message("❌ Sorry, we couldn't mark the product as sold. Please try again.")
                    
                    reset_session(from_number)
                else:
                    response.message(f"Please enter a valid number between 1 and {len(products)}.")
            except ValueError:
                response.message("Please select a product from the list or enter a valid number.")

    elif state == "AWAITING_CATEGORY":
        if list_reply_id:
            # Handle interactive list response
            category_mapping = {
                "cat_electronics": "Electronics",
                "cat_clothing": "Clothing", 
                "cat_furniture": "Furniture",
                "cat_vehicles": "Vehicles",
                "cat_home_appliances": "Home Appliances",
                "cat_real_estate": "Real Estate",
                "cat_services": "Services",
                "cat_other": "Other"
            }
            
            selected_category = category_mapping.get(list_reply_id)
            
            if selected_category:
                session = get_session(from_number)
                session["category"] = selected_category
                session["state"] = "AWAITING_CONDITION"
                set_session(from_number, session)
                
                # Create interactive buttons for condition
                condition_buttons = [
                    {"id": "cond_new", "title": "New"},
                    {"id": "cond_like_new", "title": "Used - Like New"},
                    {"id": "cond_good", "title": "Used - Good"},
                    {"id": "cond_fair", "title": "Used - Fair"}
                ]
                
                content_sid = template_manager.get_or_create_list_template(
                    template_name="condition_selection_list",
                    body="Please select the condition of your item:",
                    items=condition_buttons
                )
                
                if content_sid:
                    template_manager.send_interactive_message(from_number, content_sid)
                else:
                    # Fallback to text message
                    conditions = ["New", "Used - Like New", "Used - Good", "Used - Fair"]
                    condition_message = "Please select the condition by typing the number:\n\n" + \
                                       "\n".join([f"{i+1}. {cond}" for i, cond in enumerate(conditions)])
                    response.message(condition_message)
            else:
                response.message("Invalid category selection. Please try again.")
        else:
            # Fallback for text input
            categories = ["Electronics", "Clothing", "Furniture", "Vehicles", 
                         "Home Appliances", "Real Estate", "Services", "Other"]
            
            try:
                if incoming_text.isdigit() and 1 <= int(incoming_text) <= len(categories):
                    selected_category = categories[int(incoming_text) - 1]
                elif incoming_text in categories:
                    selected_category = incoming_text
                else:
                    raise ValueError("Invalid category")
                
                session = get_session(from_number)
                session["category"] = selected_category
                session["state"] = "AWAITING_CONDITION"
                set_session(from_number, session)
                
                # Show condition buttons
                condition_buttons = [
                    {"id": "cond_new", "title": "New"},
                    {"id": "cond_like_new", "title": "Used - Like New"},
                    {"id": "cond_good", "title": "Used - Good"},
                    {"id": "cond_fair", "title": "Used - Fair"}
                ]
                
                content_sid = template_manager.get_or_create_list_template(
                    template_name="condition_selection_list",
                    body="Please select the condition of your item:",
                    items=condition_buttons
                )
                
                if content_sid:
                    template_manager.send_interactive_message(from_number, content_sid)
                else:
                    conditions = ["New", "Used - Like New", "Used - Good", "Used - Fair"]
                    condition_message = "Please select the condition by typing the number:\n\n" + \
                                       "\n".join([f"{i+1}. {cond}" for i, cond in enumerate(conditions)])
                    response.message(condition_message)
            except:
                category_options = "\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categories)])
                response.message(f"Please select a valid category:\n\n{category_options}")
    
    elif state == "AWAITING_CONDITION":
        if list_reply_id:
            # Handle interactive button response
            condition_mapping = {
                "cond_new": "New",
                "cond_like_new": "Used - Like New",
                "cond_good": "Used - Good", 
                "cond_fair": "Used - Fair"
            }
            
            selected_condition = condition_mapping.get(list_reply_id)
            
            if selected_condition:
                session = get_session(from_number)
                session["condition"] = selected_condition
                session["state"] = "AWAITING_BUYING_PRICE"
                set_session(from_number, session)
                
                response.message("Please enter the buying price (numbers only):")
            else:
                response.message("Invalid condition selection. Please try again.")
        else:
            # Fallback for text input
            conditions = ["New", "Used - Like New", "Used - Good", "Used - Fair"]
            
            try:
                if incoming_text.isdigit() and 1 <= int(incoming_text) <= len(conditions):
                    selected_condition = conditions[int(incoming_text) - 1]
                elif incoming_text in conditions or incoming_text.lower() in [c.lower() for c in conditions]:
                    selected_condition = incoming_text
                else:
                    raise ValueError("Invalid condition")
                
                session = get_session(from_number)
                session["condition"] = selected_condition
                session["state"] = "AWAITING_BUYING_PRICE"
                set_session(from_number, session)
                
                response.message("Please enter the buying price (numbers only):")
            except:
                condition_options = "\n".join([f"{i+1}. {cond}" for i, cond in enumerate(conditions)])
                response.message(f"Please select a valid condition:\n\n{condition_options}")
    
    elif state == "AWAITING_BUYING_PRICE":        
        try:
            # Validate it's a number (can be float)
            buying_price = float(incoming_text.replace(',', ''))
            
            session = get_session(from_number)
            session["buying_price"] = buying_price
            session["state"] = "AWAITING_SELLING_PRICE"
            set_session(from_number, session)
            
            response.message("Please enter your selling price (numbers only):")
        except:
            response.message("Please enter a valid buying price (numbers only):")
    
    elif state == "AWAITING_SELLING_PRICE":
        try:
            # Validate it's a number (can be float)
            selling_price = float(incoming_text.replace(',', ''))
            
            session = get_session(from_number)
            session["selling_price"] = selling_price
            session["state"] = "AWAITING_REASON"
            set_session(from_number, session)
            
            response.message("Please provide a brief reason for selling:")
        except:
            response.message("Please enter a valid selling price (numbers only):")
    
    elif state == "AWAITING_REASON":
        if incoming_text:
            session = get_session(from_number)
            session["reason_for_selling"] = incoming_text
            session["state"] = "AWAITING_LOCATION"
            set_session(from_number, session)
            
            response.message("Please share your location (city/town):")
        else:
            response.message("I didn't catch that. Please provide a reason for selling.")

    elif state == "AWAITING_LOCATION":
        if incoming_text:
            session = get_session(from_number)
            session["location"] = incoming_text
            session["state"] = "AWAITING_CONTACT"
            set_session(from_number, session)
            
            response.message("Please provide your preferred contact information for buyers (phone or email):")
        else:
            response.message("I didn't catch that. Please provide your location.")

    elif state == "AWAITING_CONTACT":
        if incoming_text:
            session = get_session(from_number)
            session["contact"] = incoming_text
            session["state"] = "AWAITING_PAYMENT"
            set_session(from_number, session)
            
            # Display item summary
            summary = "📝 Here's your listing summary:\n\n"
            summary += f"• Description: {session['description']}\n"
            summary += f"• Category: {session['category']}\n"
            summary += f"• Condition: {session['condition']}\n"
            summary += f"• Buying Price: {session['buying_price']}\n"
            summary += f"• Selling Price: {session['selling_price']}\n"
            summary += f"• Reason for Selling: {session['reason_for_selling']}\n"
            summary += f"• Location: {session['location']}\n"
            summary += f"• Contact: {session['contact']}\n"
            
            media_count = len(session.get("media_urls", []))
            media_type = session.get("media_type", "images")
            summary += f"• Media: {media_count} {'video' if media_type == 'video' else 'image'}{'s' if media_count > 1 else ''}\n\n"
            
            response.message(summary)

            try:
                # Get the appropriate fee based on category
                category = session.get('category', '')
                ad_fee = get_fee_for_category(category)
                
                # Initiate Pesapal payment with the correct fee
                result = initiate_pesapal_payment(
                    ad_fee, 
                    from_number, 
                    f"Own Again Ad Fee - {category}"
                )
                
                if result and result.get('redirect_url'):
                    # Store pending payment for callback tracking
                    pending_payment = {
                        "user_number": from_number,
                        "order_tracking_id": result.get('order_tracking_id'),
                        "merchant_reference": result.get('merchant_reference'),
                        "created_at": datetime.utcnow(),
                        "status": "pending"
                    }
                    
                    # Store in a separate collection for tracking
                    pending_payments_collection.insert_one(pending_payment)
                    
                    # Update session state
                    session = get_session(from_number)
                    session["state"] = "PAYMENT_INITIATED"
                    session["payment_amount"] = ad_fee
                    session["order_tracking_id"] = result.get('order_tracking_id')
                    set_session(from_number, session)
                    
                    # Format fee with comma for thousands
                    formatted_fee = "{:,}".format(ad_fee)
                    
                    payment_message = f"Your ad fee is KES {formatted_fee}. Please complete your payment by visiting: {result['redirect_url']}\n\n"
                    payment_message += "We'll notify you once payment is confirmed."
                    
                    response.message(payment_message)
                else:
                    reset_session(from_number)
                    response.message(f"Sorry, we couldn't process your payment request: {result}. Please try again.")

            except Exception as e:
                reset_session(from_number)
                response.message(f"Sorry, we couldn't process your payment request: {str(e)}. Please try again.")

        else:
            response.message("I didn't catch that. Please provide your preferred contact information.")

    elif state == "PAYMENT_INITIATED":
        response.message("We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")

    else:
        # Default case
        session = get_session(from_number)
        session["state"] = "INIT"
        set_session(from_number, session)
        response.message("Welcome to Own Again! Please send me a picture to post a new item for sale, or type SOLD to mark one of your items as sold.")

    return str(response)


@app.route("/pesapal-callback", methods=["GET", "POST"])
def pesapal_callback():
    """
    Handle callbacks from Pesapal payment system
    """
    current_app.logger.info("------------------------------Pesapal Callback Received------------------------------")

    try:
        # Pesapal sends callbacks as GET requests with query parameters
        if request.method == "GET":
            order_tracking_id = request.args.get('OrderTrackingId')
            merchant_reference = request.args.get('OrderMerchantReference')

            # Extract phone number from merchant reference or session
            # Since we don't get phone number directly from Pesapal, 
            # we need to find the user by checking sessions
            user_number = None
            pending_payment = pending_payments_collection.find_one({"order_tracking_id": order_tracking_id})
            if pending_payment:
                user_number = pending_payment["user_number"]
            
            current_app.logger.info(f"Pesapal callback - Order ID: {order_tracking_id}, Merchant Ref: {merchant_reference}, User Number: {user_number}")
            
            if order_tracking_id:
                # Check payment status with Pesapal
                payment_status = check_pesapal_payment_status(order_tracking_id)
                current_app.logger.info(f"Payment status: {payment_status}")
                
                # Check if payment was successful
                if payment_status.get('payment_status_description') == 'Completed':
                    current_app.logger.info("Payment successful!")

                    # Check if this is an escrow payment
                    escrow_payment = db.escrow_payments.find_one({"order_tracking_id": order_tracking_id})

                    if escrow_payment:
                        # Use escrow service to handle payment callback
                        escrow_result = escrow_service.handle_payment_callback(
                            order_tracking_id=order_tracking_id,
                            payment_status_data=payment_status
                        )
                        current_app.logger.info(f"Escrow payment callback result: {escrow_result}")

                        # Notify buyer that payment is received
                        if escrow_result.get("success"):
                            try:
                                client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                                twilio_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
                                if not twilio_number.startswith('whatsapp:'):
                                    twilio_number = f"whatsapp:{twilio_number}"

                                buyer_message = (
                                    f"Payment received! Your funds (KES {escrow_payment.get('amount')}) "
                                    f"are now held securely in escrow.\n\n"
                                    f"Item: {escrow_payment.get('description')}\n\n"
                                    f"Once you receive and verify the item, confirm receipt to release "
                                    f"payment to the seller. You have 7 days to confirm or raise a dispute."
                                )

                                client.messages.create(
                                    body=buyer_message,
                                    from_=twilio_number,
                                    to=escrow_payment.get("buyer_phone")
                                )

                                # Also notify seller
                                seller_message = (
                                    f"Good news! A buyer has paid for your item.\n\n"
                                    f"Item: {escrow_payment.get('description')}\n"
                                    f"Amount: KES {escrow_payment.get('amount')}\n\n"
                                    f"Please arrange delivery with the buyer. "
                                    f"Funds will be released to your M-Pesa once the buyer confirms receipt."
                                )

                                client.messages.create(
                                    body=seller_message,
                                    from_=twilio_number,
                                    to=escrow_payment.get("seller_number")
                                )
                            except Exception as notify_error:
                                current_app.logger.error(f"Error sending escrow notifications: {str(notify_error)}")

                    if user_number:
                        current_app.logger.info(f"Payment received from user: {user_number}")
                        
                        # Get user session
                        session = get_session(user_number)

                        # Check if this user is awaiting payment confirmation
                        if session.get('state') == "PAYMENT_INITIATED":
                            save_product(
                                user_number=user_number,
                                media_urls=session.get("media_urls"),
                                media_type=session.get("media_type"),
                                description=session.get("description"),
                                category=session.get("category"),
                                condition=session.get("condition"),
                                buying_price=session.get("buying_price"),
                                selling_price=session.get("selling_price"),
                                reason_for_selling=session.get("reason_for_selling"),
                                location=session.get("location"),
                                contact=session.get("contact")
                            )
            
                            # Send initial confirmation message to the user
                            client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

                            # Get the Twilio number and ensure it has the whatsapp: prefix
                            twilio_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
                            if not twilio_number.startswith('whatsapp:'):
                                twilio_number = f"whatsapp:{twilio_number}"

                            initial_message = "Payment received! Your product is now listed. We're uploading your item to social media platforms - you'll receive the results shortly."
                            
                            client.messages.create(
                                body=initial_message,
                                from_=twilio_number,
                                to=user_number
                            )

                            # Start background thread for uploads
                            media_urls = session.get("media_urls")
                            media_type = session.get("media_type")
                            description = session.get("description")
                            category = session.get("category", "")
                            condition = session.get("condition", "")
                            selling_price = session.get("selling_price", "")
                            location = session.get("location", "")
                            contact = session.get("contact", "")
                            
                            upload_thread = threading.Thread(
                                target=process_social_media_uploads,
                                args=(user_number, media_urls, media_type, description, category, condition, 
                                    selling_price, location, contact)
                            )
                            upload_thread.daemon = True
                            upload_thread.start()
                            
                            # reset session
                            reset_session(user_number)
                            
                            # Clean up pending payment record
                            pending_payments_collection.delete_one({"order_tracking_id": order_tracking_id})
                            
                elif payment_status.get('payment_status_description') in ['Failed', 'Invalid']:
                    current_app.logger.info("Payment failed!")
                    
                    if user_number:
                        try:
                            client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                            twilio_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
                            if not twilio_number.startswith('whatsapp:'):
                                twilio_number = f"whatsapp:{twilio_number}"

                            message = "Your payment was unsuccessful. Please try again or contact support if the issue persists."
                            
                            client.messages.create(
                                body=message,
                                from_=twilio_number,
                                to=user_number
                            )
                        except Exception as e:
                            current_app.logger.error(f"Error sending failure notification: {str(e)}")

                    # Clean up pending payment record
                    pending_payments_collection.delete_one({"order_tracking_id": order_tracking_id})

    except Exception as e:
        current_app.logger.error(f"Error processing Pesapal callback: {str(e)}")
    
    # Return success response
    return "Payment completed, you may now close this window. ", 200

@app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint
    ---
    tags:
      - Health
    summary: Check API health status
    description: Returns the current status of the API and available endpoints
    responses:
      200:
        description: API is healthy
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            service:
              type: string
              example: Cashify API
            version:
              type: string
              example: 1.0.0
            endpoints:
              type: object
              properties:
                products:
                  type: string
                  example: /products
                fees:
                  type: string
                  example: /fees
                upload:
                  type: string
                  example: /upload/{platform}
                escrow:
                  type: string
                  example: /escrow/*
                whatsapp:
                  type: string
                  example: /whatsapp
    """
    return jsonify({
        "status": "healthy",
        "service": "Cashify API",
        "version": "1.0.0",
        "endpoints": {
            "products": "/products",
            "fees": "/fees",
            "upload": "/upload/{platform}",
            "escrow": "/escrow/*",
            "whatsapp": "/whatsapp"
        }
    }), 200

if __name__ == "__main__":
    app.run(debug=True)
