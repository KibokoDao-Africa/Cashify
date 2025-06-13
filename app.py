from flask import Flask, request, current_app, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import Message, MessagingResponse
from pymongo import MongoClient
import os
import requests
import time
import uuid
import json
import boto3
import threading
from io import BytesIO
from datetime import datetime
from payment import initiate_payment
from facebook_graph_api import upload_to_facebook, upload_to_instagram
from bson import ObjectId

app = Flask(__name__)

# MongoDB connection
mongo_client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/"))
db = mongo_client[os.getenv("MONGODB_DATABASE", "cashify")]
sessions_collection = db.sessions
products_collection = db.products

# AWS S3 Configuration
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)
S3_BUCKET = os.getenv('S3_BUCKET_NAME')

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

def get_user_products(user_number):
    """
    Get all active products for a given user
    """
    products = products_collection.find({
        "user_number": user_number,
        "status": "active",
        "sold": False
    }).sort("created_at", -1)
    
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
                # Keep backward compatibility with old image_url field
                "image_url": product.get("image_url") or (product.get("media_urls", [None])[0]),
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
            # Keep backward compatibility with old image_url field
            "image_url": product.get("image_url") or (product.get("media_urls", [None])[0]),
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

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    current_app.logger.info("------------------------------Webhook Received------------------------------")
    
    # Parse the incoming message information from Twilio's POST data
    from_number = request.form.get("From")
    incoming_text = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", "0"))

    # Retrieve or initialize a session for this user via MongoDB
    session = get_session(from_number)
    state = session.get("state", "INIT")

    response = MessagingResponse()
    current_app.logger.info(f"User {from_number} in state '{state}' sent message: {incoming_text}")

    # ---------------------------------------------------------------------
    # Reset Conversation
    # ---------------------------------------------------------------------

    if incoming_text.upper() == "RESET":
        session["state"] = "INIT"
        session.pop("media_urls", None)
        session.pop("media_type", None)
        session.pop("description", None)
        session.pop("category", None)
        session.pop("condition", None)
        session.pop("buying_price", None)
        session.pop("selling_price", None)
        session.pop("reason_for_selling", None)
        session.pop("location", None)
        session.pop("contact", None)
        session.pop("payment_amount", None)
        session.pop("transaction_id", None)
        session.pop("products", None)
        
        # Check if user has active products before mentioning SOLD option
        products = get_user_products(from_number)
        if products:
            response.message("Welcome to Cashify! Please send me up to 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
        else:
            response.message("Welcome to Cashify! Please send me up to 3 images or 1 video to post a new item for sale.")
            
        set_session(from_number, session)
        return str(response)

    # ---------------------------------------------------------------------
    # Conversation Flow
    # ---------------------------------------------------------------------

    if state == "INIT":
        if incoming_text.upper() == "SOLD":
            # User wants to mark a product as sold
            products = get_user_products(from_number)
            
            if not products:
                response.message("You don't have any active products to mark as sold.")
                return str(response)
            
            # Create a list of products for the user to choose from
            product_list = "Your active products:\n\n"
            for i, product in enumerate(products):
                product_list += f"{i+1}. {product['description']} - ${product['selling_price']}\n"
            
            product_list += "\nReply with the number of the product you want to mark as sold:"
            
            # Store products in session for reference when they select one
            session["products"] = products
            session["state"] = "AWAITING_PRODUCT_SELECTION"
            set_session(from_number, session)
            
            response.message(product_list)
        
        elif num_media > 0:
            # User has sent media files
            if num_media > 3:
                response.message("Please send up to 3 images or 1 video only.")
                return str(response)
            
            try:
                media_urls = []
                media_type = None
                
                # Process all media files
                for i in range(num_media):
                    twilio_media_url = request.form.get(f"MediaUrl{i}")
                    content_type = request.form.get(f"MediaContentType{i}", "")
                    
                    # Determine if it's a video or image
                    is_video = content_type.startswith("video/")
                    is_image = content_type.startswith("image/")
                    
                    if not is_video and not is_image:
                        response.message("Please send only images or videos.")
                        return str(response)
                    
                    # Check for mixed media types
                    if media_type is None:
                        media_type = "video" if is_video else "images"
                    elif (media_type == "video" and is_image) or (media_type == "images" and is_video):
                        response.message("Please send either images OR video, not both.")
                        return str(response)
                    
                    # For video, only allow one file
                    if is_video and num_media > 1:
                        response.message("Please send only 1 video file.")
                        return str(response)
                    
                    # Download the media from Twilio with auth
                    auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                    media_response = requests.get(twilio_media_url, auth=auth)

                    current_app.logger.info(f"Media response: {media_response}")
                    
                    if media_response.status_code != 200:
                        response.message("Sorry, I couldn't download your media. Please try again.")
                        return str(response)
                    
                    # Generate a unique filename for S3
                    extension = "mp4" if is_video else "jpg"
                    filename = f"cashify_feed_{uuid.uuid4()}.{extension}"
                    
                    # Upload the media to S3 bucket
                    public_media_url = upload_to_s3(
                        media_response.content, 
                        filename, 
                        content_type=content_type
                    )
                    
                    media_urls.append(public_media_url)
                    current_app.logger.info(f"Media uploaded to S3. Public URL: {public_media_url}")
                
                session["media_urls"] = media_urls
                session["media_type"] = media_type
                session["state"] = "AWAITING_DESCRIPTION"
                set_session(from_number, session)
                
                media_count_text = f"{len(media_urls)} {'image' if media_type == 'images' else 'video'}{'s' if len(media_urls) > 1 else ''}"
                response.message(f"Great! I received your {media_count_text}. Please enter a description for your item.")
                
            except Exception as e:
                current_app.logger.error(f"Error processing media: {str(e)}")
                response.message("Sorry, I couldn't process your media. Could you please try sending it again?")
        
        elif incoming_text.lower() == "add more" and session.get("media_urls"):
            # User wants to add more images (only if they already have images)
            current_media = session.get("media_urls", [])
            if session.get("media_type") == "video":
                response.message("You already uploaded a video. Please type RESET to start over with new media.")
            elif len(current_media) >= 3:
                response.message("You already have 3 images. Please type RESET to start over with new media.")
            else:
                remaining = 3 - len(current_media)
                response.message(f"Please send up to {remaining} more image{'s' if remaining > 1 else ''}.")
                session["state"] = "AWAITING_MORE_MEDIA"
                set_session(from_number, session)
        else:
            # Check if user has products before mentioning SOLD option
            products = get_user_products(from_number)
            if products:
                response.message("Hi! Send me up to 3 images or 1 video to post a new item for sale, or type SOLD to mark one of your items as sold.")
            else:
                response.message("Hi! Send me up to 3 images or 1 video to post a new item for sale.")

    elif state == "AWAITING_MORE_MEDIA":
        if num_media > 0:
            current_media = session.get("media_urls", [])
            
            if len(current_media) + num_media > 3:
                response.message(f"You can only add {3 - len(current_media)} more image{'s' if 3 - len(current_media) > 1 else ''}.")
                return str(response)
            
            try:
                # Process additional media files
                for i in range(num_media):
                    twilio_media_url = request.form.get(f"MediaUrl{i}")
                    content_type = request.form.get(f"MediaContentType{i}", "")
                    
                    if not content_type.startswith("image/"):
                        response.message("Please send only images when adding more media.")
                        return str(response)
                    
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
                    
                    current_media.append(public_media_url)
                
                session["media_urls"] = current_media
                session["state"] = "AWAITING_DESCRIPTION"
                set_session(from_number, session)
                
                response.message(f"Great! I now have {len(current_media)} images. Please enter a description for your item.")
                
            except Exception as e:
                current_app.logger.error(f"Error processing additional media: {str(e)}")
                response.message("Sorry, I couldn't process your images. Please try again.")
        else:
            response.message("Please send the additional images, or type CONTINUE to proceed with your current images.")

    elif state == "AWAITING_PRODUCT_SELECTION":
        try:
            selection = int(incoming_text)
            products = session.get("products", [])
            
            if 1 <= selection <= len(products):
                selected_product = products[selection - 1]
                product_id = selected_product["id"]
                
                # Mark the product as sold
                success = mark_product_as_sold(product_id)
                
                if success:
                    response.message(f"✅ Your product \"{selected_product['description']}\" has been marked as sold!")
                else:
                    response.message("❌ Sorry, we couldn't mark the product as sold. Please try again.")
                
                # Reset session
                session["state"] = "INIT"
                session.pop("products", None)
                set_session(from_number, session)
            else:
                response.message(f"Please enter a valid number between 1 and {len(products)}.")
        except ValueError:
            response.message("Please enter a valid number.")
        except Exception as e:
            current_app.logger.error(f"Error marking product as sold: {str(e)}")
            response.message("Sorry, something went wrong. Please try again.")

    elif state == "AWAITING_DESCRIPTION":
        if incoming_text:
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
            response.message("I didn't catch that. Please send me a text description for your item.")

    # ...existing code... (rest of the states remain the same until AWAITING_CONTACT)

    elif state == "AWAITING_CONTACT":
        if incoming_text:
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
            summary += "Please proceed to payment for your ad fee."
            
            response.message(summary)

            # Save complete product info to database
            try:
                product_id = save_product(
                    user_number=from_number,
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
                session["product_id"] = product_id
                set_session(from_number, session)
                current_app.logger.info(f"Product saved to database with ID: {product_id}")
            except Exception as e:
                current_app.logger.error(f"Error saving product to database: {str(e)}")

            # try:
            #     # Initiate M-Pesa payment with amount 1 KES
            #     success, result = initiate_payment(from_number, 1, "Cashify Ad Fee")
            #     
            #     if success:
            #         # Update session state
            #         session["state"] = "PAYMENT_INITIATED"
            #         session["payment_amount"] = 1
            #         
            #         response.message("Payment request sent to your phone. Please enter your M-Pesa PIN to complete the transaction. We'll notify you once payment is confirmed.")
            #     else:
            #         response.message(f"Sorry, we couldn't process your payment request: {result}. Please try again.")
            #         # reset session
            #         session["state"] = "INIT"
            #         session.pop("image", None)
            #         session.pop("description", None)
            #         session.pop("payment_amount", None)
            #         session.pop("transaction_id", None)
            #         set_session(from_number, session)
            # except Exception as e:
            #     response.message(f"Sorry, we couldn't process your payment request: {str(e)}. Please try again.")
            #     # reset session
            #     session["state"] = "INIT"
            #     session.pop("image", None)
            #     session.pop("description", None)
            #     session.pop("payment_amount", None)
            #     session.pop("transaction_id", None)
            #     set_session(from_number, session)

            # Immediately respond with a message that uploads are in progress
            response.message("Payment received! Your product is now listed. We're uploading your item to social media platforms - you'll receive the results shortly.")

            # Start a background thread to process uploads
            media_urls = session.get("media_urls")
            media_type = session.get("media_type")
            description = session.get("description")
            category = session.get("category", "")
            condition = session.get("condition", "")
            selling_price = session.get("selling_price", "")
            location = session.get("location", "")
            contact = session.get("contact", "")
            
            # Start background thread for social media uploads
            upload_thread = threading.Thread(
                target=process_social_media_uploads,
                args=(from_number, media_urls, media_type, description, category, condition, 
                      selling_price, location, contact)
            )
            upload_thread.daemon = True
            upload_thread.start()

            # reset session
            session["state"] = "INIT"
            session.pop("media_urls", None)
            session.pop("media_type", None)
            session.pop("description", None)
            session.pop("category", None)
            session.pop("condition", None)
            session.pop("buying_price", None)
            session.pop("selling_price", None)
            session.pop("reason_for_selling", None)
            session.pop("location", None)
            session.pop("contact", None)
            session.pop("payment_amount", None)
            session.pop("transaction_id", None)
            session.pop("product_id", None)
            set_session(from_number, session)

        else:
            response.message("I didn't catch that. Please provide your contact information.")
    
    elif state == "PAYMENT_INITIATED":
        response.message("We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")

    else:
        # Default case
        session["state"] = "INIT"
        set_session(from_number, session)
        response.message("Welcome to Cashify! Please send me a picture to post a new item for sale, or type SOLD to mark one of your items as sold.")

    return str(response)


@app.route("/mpesa-callback", methods=["POST"])
def mpesa_callback():
    """
    Handle callbacks from M-Pesa payment system
    """
    current_app.logger.info("------------------------------Callback Received------------------------------")

    # Get the callback data from M-Pesa
    callback_data = request.get_json()
    
    # Check if the callback contains success information
    if 'Body' in callback_data and 'stkCallback' in callback_data['Body']:
        stk_callback = callback_data['Body']['stkCallback']
        
        # Extract the result code
        result_code = stk_callback.get('ResultCode')
        
        if result_code == 0:  # Payment was successful
            current_app.logger.info("Payment successful!")
            # Extract payment details
            checkout_request_id = stk_callback.get('CheckoutRequestID')
            
            # Extract callback metadata to identify the user
            if 'CallbackMetadata' in stk_callback and 'Item' in stk_callback['CallbackMetadata']:
                items = stk_callback['CallbackMetadata']['Item']
                
                # Find the phone number in the metadata
                phone_number = None
                for item in items:
                    if item.get('Name') == 'PhoneNumber':
                        phone_number = item.get('Value')
                        break
                
                if phone_number:
                    current_app.logger.info(f"Payment received from phone number: {phone_number}")

                    # Format phone number for our session key (add "whatsapp:" prefix)
                    whatsapp_number = f"whatsapp:+{phone_number}"
                    
                    # Get user session
                    session = get_session(whatsapp_number)

                    # Check if this user is awaiting payment confirmation
                    if session.get('state') == "PAYMENT_INITIATED":
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
                            to=whatsapp_number
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
                            args=(whatsapp_number, media_urls, media_type, description, category, condition, 
                                selling_price, location, contact)
                        )
                        upload_thread.daemon = True
                        upload_thread.start()
                        
                        # reset session
                        session["state"] = "INIT"
                        session.pop("media_urls", None)
                        session.pop("media_type", None)
                        session.pop("description", None)
                        session.pop("category", None)
                        session.pop("condition", None)
                        session.pop("buying_price", None)
                        session.pop("selling_price", None)
                        session.pop("reason_for_selling", None)
                        session.pop("location", None)
                        session.pop("contact", None)
                        session.pop("payment_amount", None)
                        session.pop("transaction_id", None)
                        session.pop("product_id", None)
                        set_session(whatsapp_number, session)
    
    # Always return a success response to M-Pesa
    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }

if __name__ == "__main__":
    app.run(debug=True)
