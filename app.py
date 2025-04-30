from flask import Flask, request, current_app
from twilio.rest import Client
from twilio.twiml.messaging_response import Message, MessagingResponse
import redis
import base64
import os
import requests
from requests.auth import HTTPBasicAuth
import time
import uuid
import json

app = Flask(__name__)

redis_client = redis.Redis(host=os.getenv("REDIS_HOST"), port=int(os.getenv("REDIS_PORT")), decode_responses=True)

def get_session(user_number):
    """
    Retrieves the session for the given user from Redis. 
    If none exists, create a new session with a default 'INIT' state.
    """
    session_key = f"session:{user_number}"
    session_json = redis_client.get(session_key)
    if session_json is None:
        session = {"state": "INIT"}
        redis_client.set(session_key, json.dumps(session))
        return session
    else:
        return json.loads(session_json)

def set_session(user_number, session):
    """
    Stores/updates the session for the given user in Redis.
    """
    session_key = f"session:{user_number}"
    redis_client.set(session_key, json.dumps(session))

# get Oauth token from M-pesa
def get_mpesa_token():
    consumer_key = os.getenv('MPESA_CONSUMER_KEY')
    consumer_secret = os.getenv('MPESA_CONSUMER_SECRET')
    api_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    # make a get request using python requests liblary
    r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret))

    # return access_token from response
    return r.json()['access_token']

def lipa_na_mpesa(amount, phone_number, tx_desc):
    access_token = get_mpesa_token()
    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    timestamp = time.strftime("%Y%m%d%H%M%S")
    password = base64.b64encode((os.getenv('MPESA_BUSINESS_SHORTCODE') + os.getenv('MPESA_PASSKEY') + timestamp).encode()).decode()

    headers = { "Authorization": f"Bearer {access_token}" }
    request = {
        "BusinessShortCode": os.getenv('MPESA_BUSINESS_SHORTCODE'),
        "Password":  password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": os.getenv('MPESA_BUSINESS_SHORTCODE'),
        "PhoneNumber": phone_number,
        "CallBackURL": f"{os.getenv('BASE_URL')}/mpesa-callback",
        "AccountReference": "Cashify",
        "TransactionDesc": tx_desc,
        "Remarks": "Payment for ad fee",
    }
    response = requests.post(api_url, json = request, headers=headers)
    response = response.json()

    if 'errorMessage' in response:   # fail
        raise Exception(response['errorMessage'])
    
    elif 'ResponseCode' in response and response['ResponseCode'] == '0':   # success
        return response['ResponseDescription']

def upload_to_facebook(image_url, caption):
    """
    Upload an image to Facebook page
    """
    try:
        # Facebook API endpoint for posting to a page
        facebook_url = f"https://graph.facebook.com/v19.0/{os.getenv('FACEBOOK_PAGE_ID')}/photos"
        
        # Parameters for the Facebook post
        facebook_params = {
            "access_token": os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN'),
            "url": image_url,  # The image URL
            "caption": caption,  # The post text
            "published": "true"  # Set to true to publish immediately
        }
        
        response = requests.post(facebook_url, data=facebook_params)
        result = response.json()
        
        if 'id' in result:
            return f"https://www.facebook.com/photo/?fbid={result['id']}"
        else:
            current_app.logger.info(f"Facebook post error response: {result}")
            raise Exception(f"Failed to post to Facebook: {result.get('error', {}).get('message', 'Unknown error')}")
            
    except Exception as e:
        current_app.logger.info(f"Facebook upload error: {str(e)}")
        raise e

def upload_to_instagram(image_url, caption, story=False):
    """
    Upload an image to Instagram feed with the given caption
    """
    try:
        # Instagram API endpoints
        container_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media"
        publish_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media_publish"

        # Step 1: Create a media container
        if story:
            container_params = {
                "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                "image_url": image_url,
                "media_type": "STORIES",
                "story_sticker_ids": '[{"story_sticker_type":"MENTION","story_sticker_value":"' + caption + '"}]'
            }
        else:
            container_params = {
                "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                "caption": caption,
                "image_url": image_url
            }
        
        container_response = requests.post(container_url, data=container_params)
        container_data = container_response.json()
        
        if 'id' not in container_data:
            raise Exception(f"Failed to create media container: {container_data}")
        
        creation_id = container_data['id']
        
        # Step 2: Publish the container
        publish_params = {
            "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
            "creation_id": creation_id
        }
        
        publish_response = requests.post(publish_url, data=publish_params)
        publish_data = publish_response.json()
        
        if 'id' not in publish_data:
            raise Exception(f"Failed to publish media: {publish_data}")
        
        return publish_data['id']  # Return the Instagram post ID
        
    except Exception as e:
        current_app.logger.info(f"Instagram feed upload error: {str(e)}")
        raise e

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    current_app.logger.info("------------------------------Webhook Received------------------------------")
    

    # Parse the incoming message information from Twilio's POST data
    from_number = request.form.get("From")
    incoming_text = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", "0"))

    # Retrieve or initialize a session for this user via Redis
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

            # try:
            #     # Extract phone number from WhatsApp format (+254...)
            #     # Strip "whatsapp:" prefix and any non-digit characters
            #     clean_phone = ''.join(filter(str.isdigit, from_number.replace("whatsapp:", "")))
                
            #     # If number starts with "+" followed by country code, ensure it's in correct format for M-Pesa
            #     if clean_phone.startswith('254'):
            #         mpesa_phone = clean_phone
            #     elif clean_phone.startswith('0'):
            #         # Convert 07... to 2547...
            #         mpesa_phone = '254' + clean_phone[1:]
            #     else:
            #         mpesa_phone = clean_phone
                    
            #     # Fixed ad fee amount (you can adjust this)
            #     amount = 1  # KES
                
            #     # Initiate M-Pesa payment
            #     result = lipa_na_mpesa(amount, mpesa_phone, "Cashify Ad Fee")
                
            #     # Update session state
            #     session["state"] = "PAYMENT_INITIATED"
            #     session["payment_amount"] = amount
                
            #     response.message("Payment request sent to your phone. Please enter your M-Pesa PIN to complete the transaction. We'll notify you once payment is confirmed.")
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
                    set_session(whatsapp_number, session)
    
    # Always return a success response to M-Pesa
    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }

if __name__ == "__main__":
    app.run(debug=True)
