from flask import Flask, request, current_app, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import Message, MessagingResponse
from pymongo import MongoClient
import os
import requests
import time
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
                "user_number": product.get("user_number", "Anonymous")  # Optional: hide user number for privacy
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

    if incoming_text == "RESET":
        session["state"] = "INIT"
        session.pop("image", None)
        session.pop("description", None)
        session.pop("payment_amount", None)
        session.pop("transaction_id", None)
        response.message("Conversation reset. Please send a picture of the item you want to sell.")
        set_session(from_number, session)
        return str(response)

    # ---------------------------------------------------------------------
    # Conversation Flow
    # ---------------------------------------------------------------------

    if state == "INIT":
        if num_media > 0:
            # User has sent a media file (image)
            twilio_media_url = request.form.get("MediaUrl0")
            
            try:
                # Download the image from Twilio with auth
                auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                image_response = requests.get(twilio_media_url, auth=auth)

                current_app.logger.info(f"Image response: {image_response}")
                
                if image_response.status_code != 200:
                    response.message("Sorry, I couldn't download your image. Please try again.")
                    return str(response)
                
                # Create uploads directory if it doesn't exist
                os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
                
                # Generate a unique filename
                filename = f"cashify_feed_{uuid.uuid4()}.jpg"
                file_path = os.path.join("static", "uploads", filename)
                
                # Save the image locally
                with open(file_path, "wb") as f:
                    f.write(image_response.content)
                
                # Create a publicly accessible URL
                public_image_url = f"{os.getenv('BASE_URL')}/static/uploads/{filename}"
                current_app.logger.info(f"Media saved locally. Public URL: {public_image_url}")
                
                session["image"] = public_image_url
                session["state"] = "AWAITING_DESCRIPTION"
                set_session(from_number, session)
                response.message("Great! I received your picture. Please enter a description for your item.")
                
            except Exception as e:
                current_app.logger.error(f"Error processing media: {str(e)}")
                response.message("Sorry, I couldn't process your image. Could you please try sending it again?")
        else:
            response.message("Hi! Please send me a picture of the item you want to sell.")

    elif state == "AWAITING_DESCRIPTION":
        if incoming_text:
            session["description"] = incoming_text
            session["state"] = "AWAITING_PAYMENT"
            set_session(from_number, session)
            response.message("Awesome! Now please proceed to payment for your ad fee.")

            # Save product to database
            try:
                product_id = save_product(
                    user_number=from_number,
                    image_url=session.get("image"),
                    description=incoming_text
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

            message_body = "Payment received!\n\n"
                    
            # Get item details for social media posting
            image_url = session.get("image")
            description = session.get("description")
            
            # Create a list to track where posting succeeded
            posting_results = []
            
            # Try to post to social media platforms if we have the necessary info
            if image_url and description:
                current_app.logger.info("Posting to social media...")
                # Prepare captions for different platforms
                insta_caption = f"FOR SALE: {description}\n\nContact us to purchase this item! #Cashify #ForSale"
                story_caption = f"NEW ITEM: {description}"
                fb_caption = f"🔥 NEW LISTING 🔥\n\nFOR SALE: {description}\n\nInterested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
                
                # Try posting to each platform
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
            
            # Custom message based on posting results
            message_body += posting_results
                
            message_body += "\n\nThank you for using Cashify!"

            response.message(message_body)

            # reset session
            session["state"] = "INIT"
            session.pop("image", None)
            session.pop("description", None)
            session.pop("payment_amount", None)
            session.pop("transaction_id", None)
            session.pop("product_id", None)
            set_session(from_number, session)

        else:
            response.message("I didn't catch that. Please send me a text description for your item.")
    
    elif state == "PAYMENT_INITIATED":
        response.message("We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")

    else:
        # Default case
        session["state"] = "INIT"
        set_session(from_number, session)
        response.message("Welcome to Cashify! Please send a picture of the item you want to sell.")

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

                    message_body = "Payment received!\n\n"
                    
                    # Check if this user is awaiting payment confirmation
                    if session.get('state') == "PAYMENT_INITIATED":
                        # Get item details for social media posting
                        image_url = session.get("image")
                        description = session.get("description")
                        
                        # Create a list to track where posting succeeded
                        posting_results = []
                        
                        # Try to post to social media platforms if we have the necessary info
                        if image_url and description:
                            current_app.logger.info("Posting to social media...")
                            # Prepare captions for different platforms
                            insta_caption = f"FOR SALE: {description}\n\nContact us to purchase this item! #Cashify #ForSale"
                            story_caption = f"NEW ITEM: {description}"
                            fb_caption = f"🔥 NEW LISTING 🔥\n\nFOR SALE: {description}\n\nInterested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
                            
                            # Try posting to each platform
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
                        
                        # Save the updated session
                        set_session(whatsapp_number, session)
                        
                        # Custom message based on posting results
                        message_body += posting_results
                        
                    message_body += "\n\nThank you for using Cashify!"

                    # Send confirmation message to the user
                    client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

                    # Get the Twilio number and ensure it has the whatsapp: prefix
                    twilio_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
                    if not twilio_number.startswith('whatsapp:'):
                        twilio_number = f"whatsapp:{twilio_number}"

                    current_app.logger.info(f"Sending message to {whatsapp_number}: {message_body}")

                    message = client.messages.create(
                        body=message_body,
                        from_=twilio_number,
                        to=whatsapp_number
                    )

                    current_app.logger.info(f"Message sent with SID: {message.sid}")

                    # reset session
                    session["state"] = "INIT"
                    session.pop("image", None)
                    session.pop("description", None)
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