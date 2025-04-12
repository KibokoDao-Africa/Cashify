from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import Message, MessagingResponse
import redis
import base64
import os
import requests
from requests.auth import HTTPBasicAuth
import time
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
        "CallBackURL": f"{os.getenv('CALLBACK_URL')}/mpesa-callback",
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

def upload_to_instagram_feed(image_url, caption):
    """
    Upload an image to Instagram feed with the given caption
    """
    try:
        # Instagram API endpoints
        container_url = f"https://graph.facebook.com/v17.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media"
        publish_url = f"https://graph.facebook.com/v17.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media_publish"
        
        # Step 1: Create a media container
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
        print(f"Instagram feed upload error: {str(e)}")
        raise e

def upload_to_instagram_story(image_url, caption):
    """
    Upload an image to Instagram Story
    """
    try:
        # Instagram API endpoint for Stories
        story_url = f"https://graph.facebook.com/v17.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/stories"
        
        # For stories we need a publicly accessible image URL
        story_params = {
            "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
            "image_url": image_url,
            "caption": caption
        }
        
        response = requests.post(story_url, data=story_params)
        result = response.json()
        
        if 'id' in result:
            return result['id']
        else:
            print(f"Story creation error response: {result}")
            raise Exception(f"Failed to create story: {result.get('error', {}).get('message', 'Unknown error')}")
        
    except Exception as e:
        print(f"Instagram story upload error: {str(e)}")
        raise e

def upload_to_facebook(image_url, caption):
    """
    Upload an image to Facebook page
    """
    try:
        # Facebook API endpoint for posting to a page
        facebook_url = f"https://graph.facebook.com/v17.0/{os.getenv('FACEBOOK_PAGE_ID')}/photos"
        
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
            return result['id']  # Return post ID
        else:
            print(f"Facebook post error response: {result}")
            raise Exception(f"Failed to post to Facebook: {result.get('error', {}).get('message', 'Unknown error')}")
            
    except Exception as e:
        print(f"Facebook upload error: {str(e)}")
        raise e

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    # Parse the incoming message information from Twilio's POST data
    from_number = request.form.get("From")
    incoming_text = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", "0"))

    # Retrieve or initialize a session for this user via Redis
    session = get_session(from_number)
    state = session.get("state", "INIT")

    response = MessagingResponse()
    print(f"User {from_number} in state '{state}' sent message: {incoming_text}")

    # ---------------------------------------------------------------------
    # Conversation Flow
    # ---------------------------------------------------------------------

    if state == "INIT":
        if num_media > 0:
            # User has sent a media file (image)
            media_url = request.form.get("MediaUrl0")
            session["image"] = media_url
            session["state"] = "AWAITING_DESCRIPTION"
            response.message("Great! I received your picture. Please enter a description for your item.")
        else:
            response.message("Hi! Please send me a picture of the item you want to sell.")

    elif state == "AWAITING_DESCRIPTION":
        if incoming_text:
            session["description"] = incoming_text
            session["state"] = "AWAITING_PAYMENT"
            response.message("Awesome! Now please proceed to payment for your ad fee. (Payment integration coming soon.)")
        else:
            response.message("I didn't catch that. Please send me a text description for your item.")

    elif state == "AWAITING_PAYMENT":
        try:
            # Extract phone number from WhatsApp format (+254...)
            # Strip "whatsapp:" prefix and any non-digit characters
            clean_phone = ''.join(filter(str.isdigit, from_number.replace("whatsapp:", "")))
            
            # If number starts with "+" followed by country code, ensure it's in correct format for M-Pesa
            if clean_phone.startswith('254'):
                mpesa_phone = clean_phone
            elif clean_phone.startswith('0'):
                # Convert 07... to 2547...
                mpesa_phone = '254' + clean_phone[1:]
            else:
                mpesa_phone = clean_phone
                
            # Fixed ad fee amount (you can adjust this)
            amount = 1  # KES
            
            # Initiate M-Pesa payment
            result = lipa_na_mpesa(amount, mpesa_phone, "Cashify Ad Fee")
            
            # Update session state
            session["state"] = "PAYMENT_INITIATED"
            session["payment_amount"] = amount
            
            response.message("Payment request sent to your phone. Please enter your M-Pesa PIN to complete the transaction. We'll notify you once payment is confirmed.")
        except Exception as e:
            response.message(f"Sorry, we couldn't process your payment request: {str(e)}. Please try again.")
    
    elif state == "PAYMENT_INITIATED":
        response.message("We're still waiting for your payment confirmation. Please complete the M-Pesa prompt on your phone.")

    else:
        # Default case
        session["state"] = "INIT"
        response.message("Welcome to Cashify! Please send a picture of the item you want to sell.")

    # Save the updated session back to Redis
    set_session(from_number, session)
    return str(response)

@app.route("/mpesa-callback", methods=["POST"])
def mpesa_callback():
    """
    Handle callbacks from M-Pesa payment system
    """
    # Get the callback data from M-Pesa
    callback_data = request.get_json()
    
    # Check if the callback contains success information
    if 'Body' in callback_data and 'stkCallback' in callback_data['Body']:
        stk_callback = callback_data['Body']['stkCallback']
        
        # Extract the result code
        result_code = stk_callback.get('ResultCode')
        
        if result_code == 0:  # Payment was successful
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
                    # Format phone number for our session key (add "whatsapp:" prefix)
                    whatsapp_number = f"whatsapp:+{phone_number}"
                    
                    # Get user session
                    session = get_session(whatsapp_number)
                    
                    # Check if this user is awaiting payment confirmation
                    if session.get('state') == "PAYMENT_INITIATED":
                        # Update session
                        session['state'] = "PAYMENT_COMPLETED"
                        session['transaction_id'] = checkout_request_id
                        set_session(whatsapp_number, session)
                        
                        # Send confirmation message to the user
                        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                        
                        message = client.messages.create(
                            body="Payment received! Your ad is now being processed and will be live shortly.",
                            from_=os.getenv('TWILIO_WHATSAPP_NUMBER'),
                            to=whatsapp_number
                        )
    
    # Always return a success response to M-Pesa
    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }

@app.route("/mpesa-callback", methods=["POST"])
def mpesa_callback():
    """
    Handle callbacks from M-Pesa payment system
    """
    # Get the callback data from M-Pesa
    callback_data = request.get_json()
    
    # Check if the callback contains success information
    if 'Body' in callback_data and 'stkCallback' in callback_data['Body']:
        stk_callback = callback_data['Body']['stkCallback']
        
        # Extract the result code
        result_code = stk_callback.get('ResultCode')
        
        if result_code == 0:  # Payment was successful
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
                            # Prepare captions for different platforms
                            insta_caption = f"FOR SALE: {description}\n\nContact us to purchase this item! #Cashify #ForSale"
                            story_caption = f"NEW ITEM: {description}"
                            fb_caption = f"🔥 NEW LISTING 🔥\n\nFOR SALE: {description}\n\nInterested? Contact us through WhatsApp! #Cashify #MarketplaceAlternative"
                            
                            # Try posting to each platform
                            try:
                                upload_to_instagram_feed(image_url, insta_caption)
                                posting_results.append("Ad successfully posted to Instagram feed")
                            except Exception as e:
                                posting_results.append(f"Error posting to Instagram: {str(e)}")
                                
                            try:
                                upload_to_instagram_story(image_url, story_caption)
                                posting_results.append("Ad successfully posted to Instagram Stories")
                            except Exception as e:
                                posting_results.append(f"Error posting to Instagram Stories: {str(e)}")
                                
                            try:
                                upload_to_facebook(image_url, fb_caption)
                                posting_results.append("Ad successfully posted to Facebook")
                            except Exception as e:
                                posting_results.append(f"Error posting to Facebook: {str(e)}")
                        
                        # Save the updated session
                        set_session(whatsapp_number, session)
                        
                        # Custom message based on posting results
                        message_body += "\n".join(posting_results)
                        
                    message_body += "\n\nThank you for using Cashify!"

                    # Send confirmation message to the user
                    client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
                    message = client.messages.create(
                        body=message_body,
                        from_=os.getenv('TWILIO_WHATSAPP_NUMBER'),
                        to=whatsapp_number
                    )

                    # reset session
                    session["state"] = "INIT"
                    session.pop("image", None)
                    session.pop("description", None)
                    session.pop("payment_amount", None)
                    session.pop("transaction_id", None)
    
    # Always return a success response to M-Pesa
    return {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }

if __name__ == "__main__":
    app.run(debug=True)
