from flask import Flask, request, current_app, jsonify
import requests
from pymongo import MongoClient
import os
import uuid
import json
from datetime import datetime
from payment import initiate_payment
from facebook_graph_api import upload_to_facebook, upload_to_instagram

app = Flask(__name__)

# MongoDB connection
mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/"))
db = mongo_client[os.getenv("MONGODB_DATABASE", "cashify")]
sessions_collection = db.sessions
products_collection = db.products

# Meta WhatsApp API Configuration
WHATSAPP_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to, message_text):
    """
    Send a text message using Meta WhatsApp Business API
    """
    headers = {
        'Authorization': f'Bearer {WHATSAPP_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message_text
        }
    }
    
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
        response.raise_for_status()
        current_app.logger.info(f"Message sent successfully to {to}")
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to send message: {str(e)}")
        return None

def download_media_from_meta(media_id):
    """
    Download media from Meta's WhatsApp API
    """
    # First, get the media URL
    media_url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}'}
    
    try:
        # Get media info
        media_response = requests.get(media_url, headers=headers)
        media_response.raise_for_status()
        media_info = media_response.json()
        
        # Download the actual media file
        file_url = media_info.get('url')
        if file_url:
            file_response = requests.get(file_url, headers=headers)
            file_response.raise_for_status()
            return file_response.content
        
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to download media: {str(e)}")
        return None

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

def save_product(user_number, image_url, description):
    """
    Save a product to the database
    """
    product = {
        "user_number": user_number,
        "image_url": image_url,
        "description": description,
        "created_at": datetime.utcnow(),
        "status": "active"
    }
    
    result = products_collection.insert_one(product)
    current_app.logger.info(f"Product saved with ID: {result.inserted_id}")
    return str(result.inserted_id)

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
        products_cursor = products_collection.find(
            {"status": "active"}
        ).sort("created_at", -1).skip(skip).limit(limit)
        
        products = []
        for product in products_cursor:
            # Convert ObjectId to string and format the product
            product_data = {
                "id": str(product["_id"]),
                "description": product["description"],
                "image_url": product["image_url"],
                "created_at": product["created_at"].isoformat() if product.get("created_at") else None,
                "user_number": product.get("user_number", "Anonymous")
            }
            products.append(product_data)
        
        # Get total count for pagination info
        total_products = products_collection.count_documents({"status": "active"})
        
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
        from bson import ObjectId
        
        product = products_collection.find_one({"_id": ObjectId(product_id)})
        
        if not product:
            return jsonify({
                "success": False,
                "error": "Product not found"
            }), 404
        
        product_data = {
            "id": str(product["_id"]),
            "description": product["description"],
            "image_url": product["image_url"],
            "created_at": product["created_at"].isoformat() if product.get("created_at") else None,
            "user_number": product.get("user_number", "Anonymous")
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

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """
    Webhook for Meta WhatsApp Business API
    """
    if request.method == "GET":
        # Webhook verification
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode and token:
            if mode == "subscribe" and token == VERIFY_TOKEN:
                current_app.logger.info("Webhook verified successfully!")
                return challenge
            else:
                current_app.logger.warning("Webhook verification failed!")
                return "Verification failed", 403
        
        return "Bad request", 400
    
    elif request.method == "POST":
        # Handle incoming messages
        data = request.get_json()
        current_app.logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")
        
        # Check if this is a WhatsApp message
        if data.get("object") == "whatsapp_business_account":
            entries = data.get("entry", [])
            
            for entry in entries:
                changes = entry.get("changes", [])
                
                for change in changes:
                    value = change.get("value", {})
                    
                    # Check for messages
                    if "messages" in value:
                        messages = value["messages"]
                        
                        for message in messages:
                            process_whatsapp_message(message, value)
        
        return "OK", 200

def process_whatsapp_message(message, value):
    """
    Process incoming WhatsApp message
    """
    from_number = message.get("from")
    message_id = message.get("id")
    timestamp = message.get("timestamp")
    
    # Get message content
    message_type = message.get("type")
    message_text = ""
    media_id = None
    
    if message_type == "text":
        message_text = message.get("text", {}).get("body", "").strip()
    elif message_type == "image":
        media_id = message.get("image", {}).get("id")
        message_text = message.get("image", {}).get("caption", "").strip()
    
    current_app.logger.info(f"Processing message from {from_number}: {message_text}")
    
    # Get or create session
    session = get_session(from_number)
    state = session.get("state", "INIT")
    
    # Handle reset command
    if message_text.upper() == "RESET":
        session["state"] = "INIT"
        session.pop("image", None)
        session.pop("description", None)
        session.pop("payment_amount", None)
        session.pop("transaction_id", None)
        session.pop("product_id", None)
        send_whatsapp_message(from_number, "Conversation reset. Please send a picture of the item you want to sell.")
        set_session(from_number, session)
        return
    
    # Handle conversation flow
    if state == "INIT":
        if message_type == "image" and media_id:
            # Download and save image
            try:
                image_content = download_media_from_meta(media_id)
                if image_content:
                    # Create uploads directory if it doesn't exist
                    os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
                    
                    # Generate unique filename
                    filename = f"cashify_feed_{uuid.uuid4()}.jpg"
                    file_path = os.path.join("static", "uploads", filename)
                    
                    # Save image locally
                    with open(file_path, "wb") as f:
                        f.write(image_content)
                    
                    # Create public URL
                    public_image_url = f"{os.getenv('BASE_URL')}/static/uploads/{filename}"
                    current_app.logger.info(f"Media saved locally. Public URL: {public_image_url}")
                    
                    session["image"] = public_image_url
                    session["state"] = "AWAITING_DESCRIPTION"
                    set_session(from_number, session)
                    
                    send_whatsapp_message(from_number, "Great! I received your picture. Please enter a description for your item.")
                else:
                    send_whatsapp_message(from_number, "Sorry, I couldn't process your image. Please try again.")
            except Exception as e:
                current_app.logger.error(f"Error processing image: {str(e)}")
                send_whatsapp_message(from_number, "Sorry, I couldn't process your image. Please try again.")
        else:
            send_whatsapp_message(from_number, "Hi! Please send me a picture of the item you want to sell.")
    
    elif state == "AWAITING_DESCRIPTION":
        if message_text:
            session["description"] = message_text
            session["state"] = "AWAITING_PAYMENT"
            set_session(from_number, session)
            
            # Save product to database
            try:
                product_id = save_product(
                    user_number=from_number,
                    image_url=session.get("image"),
                    description=message_text
                )
                session["product_id"] = product_id
                set_session(from_number, session)
                current_app.logger.info(f"Product saved to database with ID: {product_id}")
            except Exception as e:
                current_app.logger.error(f"Error saving product: {str(e)}")
            
            # For now, skip payment and proceed directly to posting
            # You can uncomment the M-Pesa integration later
            # send_whatsapp_message(from_number, "Awesome! Now please proceed to payment for your ad fee.")
            
            # Process posting immediately (simulating successful payment)
            message_body = "Payment received!\n\n"
            
            image_url = session.get("image")
            description = session.get("description")
            posting_results = []
            
            if image_url and description:
                current_app.logger.info("Posting to social media...")
                
                insta_caption = f"FOR SALE: {description}\n\nContact us to purchase this item! #Cashify #ForSale"
                story_caption = f"NEW ITEM: {description}"
                fb_caption = f"🔥 NEW LISTING 🔥\n\nFOR SALE: {description}\n\nInterested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
                
                try:
                    link = upload_to_facebook(image_url, fb_caption)
                    posting_results.append("Facebook post created with link: " + link)
                except Exception as e:
                    posting_results.append(f"Error posting to Facebook: {str(e)}")

                try:
                    id = upload_to_instagram(image_url, insta_caption)
                    posting_results.append("Instagram post created with ID: " + id)
                except Exception as e:
                    posting_results.append(f"Error posting to Instagram: {str(e)}")
                    
                try:
                    id = upload_to_instagram(image_url, story_caption, story=True)
                    posting_results.append("Instagram story created with ID: " + id)
                except Exception as e:
                    posting_results.append(f"Error posting to Instagram: {str(e)}")

                posting_results = "\n".join(posting_results)
                current_app.logger.info(f"Social media posting results: {posting_results}")
            
            message_body += posting_results
            message_body += "\n\nThank you for using Cashify!"
            
            send_whatsapp_message(from_number, message_body)
            
            # Reset session
            session["state"] = "INIT"
            session.pop("image", None)
            session.pop("description", None)
            session.pop("payment_amount", None)
            session.pop("transaction_id", None)
            session.pop("product_id", None)
            set_session(from_number, session)
        else:
            send_whatsapp_message(from_number, "I didn't catch that. Please send me a text description for your item.")
    
    elif state == "PAYMENT_INITIATED":
        send_whatsapp_message(from_number, "We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")
    
    else:
        session["state"] = "INIT"
        set_session(from_number, session)
        send_whatsapp_message(from_number, "Welcome to Cashify! Please send a picture of the item you want to sell.")

@app.route("/mpesa-callback", methods=["POST"])
def mpesa_callback():
    """
    Handle callbacks from M-Pesa payment system
    """
    current_app.logger.info("------------------------------Callback Received------------------------------")
    
    callback_data = request.get_json()
    
    if 'Body' in callback_data and 'stkCallback' in callback_data['Body']:
        stk_callback = callback_data['Body']['stkCallback']
        result_code = stk_callback.get('ResultCode')
        
        if result_code == 0:  # Payment successful
            current_app.logger.info("Payment successful!")
            
            if 'CallbackMetadata' in stk_callback and 'Item' in stk_callback['CallbackMetadata']:
                items = stk_callback['CallbackMetadata']['Item']
                
                phone_number = None
                for item in items:
                    if item.get('Name') == 'PhoneNumber':
                        phone_number = item.get('Value')
                        break
                
                if phone_number:
                    current_app.logger.info(f"Payment received from phone number: {phone_number}")
                    
                    # Remove country code prefix if present for Meta API
                    if phone_number.startswith('254'):
                        phone_number = phone_number[3:]
                    elif phone_number.startswith('+254'):
                        phone_number = phone_number[4:]
                    
                    session = get_session(phone_number)
                    
                    if session.get('state') == "PAYMENT_INITIATED":
                        message_body = "Payment received!\n\n"
                        
                        # Get item details for social media posting
                        image_url = session.get("image")
                        description = session.get("description")
                        posting_results = []
                        
                        if image_url and description:
                            current_app.logger.info("Posting to social media...")
                            
                            insta_caption = f"FOR SALE: {description}\n\nContact us to purchase this item! #Cashify #ForSale"
                            story_caption = f"NEW ITEM: {description}"
                            fb_caption = f"🔥 NEW LISTING 🔥\n\nFOR SALE: {description}\n\nInterested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
                            
                            try:
                                link = upload_to_facebook(image_url, fb_caption)
                                posting_results.append("Facebook post created with link: " + link)
                            except Exception as e:
                                posting_results.append(f"Error posting to Facebook: {str(e)}")

                            try:
                                id = upload_to_instagram(image_url, insta_caption)
                                posting_results.append("Instagram post created with ID: " + id)
                            except Exception as e:
                                posting_results.append(f"Error posting to Instagram: {str(e)}")

                            try:
                                id = upload_to_instagram(image_url, story_caption, story=True)
                                posting_results.append("Instagram story created with ID: " + id)
                            except Exception as e:
                                posting_results.append(f"Error posting to Instagram: {str(e)}")

                            posting_results = "\n".join(posting_results)
                            current_app.logger.info(f"Social media posting results: {posting_results}")
                        
                        message_body += posting_results
                        message_body += "\n\nThank you for using Cashify!"
                        
                        send_whatsapp_message(phone_number, message_body)
                        
                        # Reset session
                        session["state"] = "INIT"
                        session.pop("image", None)
                        session.pop("description", None)
                        session.pop("payment_amount", None)
                        session.pop("transaction_id", None)
                        session.pop("product_id", None)
                        set_session(phone_number, session)
    
    return {"ResultCode": 0, "ResultDesc": "Accepted"}

# Static file serving (for uploaded images)
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join('static', 'uploads'), filename)

if __name__ == "__main__":
    app.run(debug=True)
    