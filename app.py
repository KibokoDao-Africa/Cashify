from flask import Flask, request, current_app, jsonify
from flask_cors import CORS
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from pymongo import MongoClient
import os
import requests
import uuid
import boto3
import threading
from io import BytesIO
from datetime import datetime, timedelta
from payment import initiate_pesapal_payment, check_pesapal_payment_status
from facebook_graph_api import upload_to_facebook, upload_to_instagram
from bson import ObjectId

app = Flask(__name__)

# Configure CORS with specific settings
CORS(app, resources={
    r"/products*": {"origins": "*"},
    r"/whatsapp": {"origins": "*"},
    r"/pesapal-callback": {"origins": "*"},
    r"/fees": {"origins": "*"},
    r"/escrow/*": {"origins": "*"}
})

# MongoDB connection
mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/"))
db = mongo_client[os.getenv("MONGODB_DATABASE", "cashify")]
sessions_collection = db.sessions
products_collection = db.products
fees_collection = db.fees  # Collection for category fees
pending_payments_collection = db.pending_payments
escrow_payments_collection = db.escrow_payments

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
        
        insta_caption = base_caption + "Contact us to purchase this item! #Cashify #ForSale"
        story_caption = f"NEW ITEM: {description} - {selling_price}"
        fb_caption = "🔥 NEW LISTING 🔥\n\n" + base_caption + "Interested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
        
        is_video = media_type == "video"
        
        # Try posting to each platform
        try:
            link = upload_to_facebook(media_urls=media_urls, is_video=is_video, caption=fb_caption)
            posting_results.append("Facebook post created with link: " + link)
        except Exception as e:
            posting_results.append(f"Error posting to Facebook: {str(e)}")

        try:
            id = upload_to_instagram(media_urls=media_urls, is_video=is_video, caption=insta_caption)
            posting_results.append("Instagram post created with ID: " + id)
        except Exception as e:
            posting_results.append(f"Error posting to Instagram: {str(e)}")
            
        try:
            # For stories, use only the first media file
            story_media = [media_urls[0]] if media_urls else []
            id = upload_to_instagram(media_urls=story_media, is_video=is_video, caption=story_caption, story=True)
            posting_results.append("Instagram story created with ID: " + id)
        except Exception as e:
            posting_results.append(f"Error posting to Instagram stories: {str(e)}")

        # Send follow-up message with results
        follow_up_message = "✅ Social Media Upload Results:\n\n"
        follow_up_message += "\n".join(posting_results)
        follow_up_message += "\n\nThank you for using Cashify!"
        
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
    """
    Endpoint to create a new product listing
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
    """
    Public endpoint to get all products
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
    """
    Get a specific product by ID
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
    """
    Endpoint to get or update category fees
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
    
@app.route("/escrow/pay", methods=["POST"])
def create_escrow_payment():
    """
    Endpoint for buyers to pay for an item.
    The money will be held in escrow until the item is confirmed as received.
    """
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ["product_id", "buyer_phone"]
        for field in required_fields:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400
        
        # Get product details
        product = products_collection.find_one({"_id": ObjectId(data["product_id"])})
        if not product:
            return jsonify({"success": False, "error": "Product not found"}), 404
            
        if product.get("sold", False) or product.get("status") == "reserved":
            return jsonify({"success": False, "error": "Product is not available"}), 400
            
        # Format buyer phone number
        from payment import format_phone_number
        buyer_phone = format_phone_number(data["buyer_phone"])
        
        # Get payment amount from product
        amount = float(product.get("selling_price", 0))
        if amount <= 0:
            return jsonify({"success": False, "error": "Invalid product price"}), 400
        
        # Create escrow payment record
        escrow_payment = {
            "product_id": data["product_id"],
            "seller_number": product["user_number"],
            "buyer_phone": buyer_phone,
            "amount": amount,
            "description": f"Purchase of {product['description']}",
            "status": "pending",
            "created_at": datetime.utcnow()
        }
        
        # Insert escrow payment record
        result = escrow_payments_collection.insert_one(escrow_payment)
        escrow_id = str(result.inserted_id)
        
        # Initiate payment with Pesapal
        from payment import initiate_pesapal_payment
        payment_result = initiate_pesapal_payment(
            amount, 
            buyer_phone, 
            f"Purchase of {product['description']}"
        )
        
        if payment_result and payment_result.get('redirect_url'):
            # Update escrow payment with Pesapal tracking details
            escrow_payments_collection.update_one(
                {"_id": result.inserted_id},
                {"$set": {
                    "order_tracking_id": payment_result.get('order_tracking_id'),
                    "merchant_reference": payment_result.get('merchant_reference')
                }}
            )
            
            # Temporarily mark the product as reserved
            products_collection.update_one(
                {"_id": ObjectId(data["product_id"])},
                {"$set": {"status": "reserved", "reserved_by": escrow_id}}
            )
            
            return jsonify({
                "success": True,
                "data": {
                    "escrow_id": escrow_id,
                    "payment_url": payment_result['redirect_url'],
                    "amount": amount
                }
            })
        else:
            # Clean up escrow record if payment initiation fails
            escrow_payments_collection.delete_one({"_id": result.inserted_id})
            return jsonify({
                "success": False,
                "error": "Payment initiation failed"
            }), 500
            
    except Exception as e:
        current_app.logger.error(f"Error creating escrow payment: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to create escrow payment"
        }), 500

@app.route("/escrow/release", methods=["POST"])
def release_escrow_payment():
    """
    Endpoint to release funds to a seller after confirming that 
    the buyer has received the item.
    """
    try:
        data = request.json
        
        # Validate required fields
        if "escrow_id" not in data:
            return jsonify({"success": False, "error": "Missing escrow_id"}), 400
        
        # Get escrow payment details
        escrow_payment = escrow_payments_collection.find_one({"_id": ObjectId(data["escrow_id"])})
        if not escrow_payment:
            return jsonify({"success": False, "error": "Escrow payment not found"}), 404
            
        # Check if payment is already processed
        if escrow_payment.get("status") == "released":
            return jsonify({"success": False, "error": "Payment has already been released"}), 400
        
        # Check if payment is confirmed
        if escrow_payment.get("status") != "paid":
            return jsonify({"success": False, "error": "Payment is not confirmed yet"}), 400
            
        # Get product details
        product = products_collection.find_one({"_id": ObjectId(escrow_payment["product_id"])})
        if not product:
            return jsonify({"success": False, "error": "Associated product not found"}), 404
        
        # Send money to seller using AfricasTalking
        from payment import send_money_via_at
        seller_phone = product["user_number"]
        amount = escrow_payment["amount"]
        
        payment_result = send_money_via_at(
            seller_phone,
            amount,
            f"Payment for {product['description']}"
        )

        current_app.logger.info(f"AfricasTalking payment result: {payment_result}")
        
        if payment_result and payment_result.get("status") == "success":
            # Update escrow payment status
            escrow_payments_collection.update_one(
                {"_id": ObjectId(data["escrow_id"])},
                {"$set": {
                    "status": "released",
                    "released_at": datetime.utcnow(),
                    "payment_reference": payment_result.get("data", {}).get("transactionId")
                }}
            )
            
            # Mark product as sold
            products_collection.update_one(
                {"_id": ObjectId(escrow_payment["product_id"])},
                {"$set": {
                    "status": "sold",
                    "sold": True,
                    "sold_at": datetime.utcnow(),
                    "sold_to": escrow_payment.get("buyer_phone")
                }}
            )
            
            return jsonify({
                "success": True,
                "data": {
                    "message": "Payment released to seller",
                    "transaction_id": payment_result.get("data", {}).get("transactionId")
                }
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to release payment"
            }), 500
            
    except Exception as e:
        current_app.logger.error(f"Error releasing escrow payment: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Failed to release escrow payment"
        }), 500

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    current_app.logger.info("------------------------------Webhook Received------------------------------")
    
    # Parse the incoming message information from Twilio's POST data
    from_number = request.form.get("From")
    incoming_text = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", "0"))

    # Create response object
    response = MessagingResponse()

    # ---------------------------------------------------------------------
    # Reset Conversation
    # ---------------------------------------------------------------------

    if incoming_text.upper() == "RESET":
        reset_session(from_number)
        response.message("Welcome to Cashify! Please send at least 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
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
                    
                    filename = f"cashify_feed_{uuid.uuid4()}.mp4"
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
                    
                    filename = f"cashify_feed_{uuid.uuid4()}.jpg"
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
                    
                    # Create a list of products for the user to choose from
                    product_list = "Your products (7+ days old) available to mark as sold:\n\n"
                    for i, product in enumerate(products):
                        product_list += f"{i+1}. {product['description']} - ${product['selling_price']}\n"
                    
                    product_list += "\nReply with the number of the product you want to mark as sold:"
                    
                    # Store products in session for reference when they select one - get fresh session for update
                    session = get_session(from_number)
                    session["products"] = products
                    session["state"] = "AWAITING_PRODUCT_SELECTION"
                    set_session(from_number, session)
                    
                    response.message(product_list)
                else:
                    # Send a welcome message
                    response.message("Hi! Please send at least 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
            elif current_count < 3 and get_session(from_number).get("media_type") == "images":
                # Remind user to add more images
                response.message(f"Please send {3 - current_count} more image{'s' if needed > 1 else ''} to meet the minimum requirement, or type RESET to start over.")
            else:
                # Save incoming text as description
                if incoming_text:
                    session = get_session(from_number)
                    session["description"] = incoming_text
                    session["state"] = "AWAITING_CATEGORY"
                    set_session(from_number, session)
                    
                    # Send category options
                    categories = ["Electronics", "Clothing", "Furniture", "Vehicles", 
                                "Home Appliances", "Real Estate", "Services", "Other"]
                    category_message = "Please select a category for your item by typing the number:\n\n" + \
                                    "\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categories)])
                    
                    response.message(category_message)
                else:
                    response.message("I didn't catch that. Please send more images, or a text description for your item.")                

    elif state == "AWAITING_PRODUCT_SELECTION":
        try:
            selection = int(incoming_text)
            products = get_session(from_number).get("products", [])
            
            if 1 <= selection <= len(products):
                selected_product = products[selection - 1]
                product_id = selected_product["id"]
                
                # Mark the product as sold
                success = mark_product_as_sold(product_id)
                
                if success:
                    response.message(f"✅ Your product \"{selected_product['description']}\" has been marked as sold!")
                else:
                    response.message("❌ Sorry, we couldn't mark the product as sold. Please try again.")
                
                reset_session(from_number)
            else:
                response.message(f"Please enter a valid number between 1 and {len(products)}.")
        except ValueError:
            response.message("Please enter a valid number.")
        except Exception as e:
            current_app.logger.error(f"Error marking product as sold: {str(e)}")
            response.message("Sorry, something went wrong. Please try again.")

    elif state == "AWAITING_CATEGORY":
        categories = ["Electronics", "Clothing", "Furniture", "Vehicles", 
                     "Home Appliances", "Real Estate", "Services", "Other"]
        
        try:
            # Handle both number input and text input
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
            
            # Send condition options
            conditions = ["New", "Used - Like New", "Used - Good", "Used - Fair"]
            condition_message = "Please select the condition by typing the number:\n\n" + \
                               "\n".join([f"{i+1}. {cond}" for i, cond in enumerate(conditions)])
            
            response.message(condition_message)
        except:
            category_options = "\n".join([f"{i+1}. {cat}" for i, cat in enumerate(categories)])
            response.message(f"Please select a valid category number or name:\n\n{category_options}")
    
    elif state == "AWAITING_CONDITION":
        # Get fresh session
        conditions = ["New", "Used - Like New", "Used - Good", "Used - Fair"]
        
        try:
            # Handle both number input and text input
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
            response.message(f"Please select a valid condition number or name:\n\n{condition_options}")
    
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
                    f"Cashify Ad Fee - {category}"
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
            response.message("I didn't catch that. Please provide your contact information.")
    
    elif state == "PAYMENT_INITIATED":
        response.message("We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")

    else:
        # Default case
        session = get_session(from_number)
        session["state"] = "INIT"
        set_session(from_number, session)
        response.message("Welcome to Cashify! Please send me a picture to post a new item for sale, or type SOLD to mark one of your items as sold.")

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
                        # Update escrow payment status
                        db.escrow_payments.update_one(
                            {"_id": escrow_payment["_id"]},
                            {"$set": {
                                "status": "paid",
                                "paid_at": datetime.utcnow(),
                                "payment_details": payment_status
                            }}
                        )

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

if __name__ == "__main__":
    app.run(debug=True)
