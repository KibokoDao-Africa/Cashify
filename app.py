from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import redis
import os
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
        # TODO: Integrate payment processing here
        # For now, we'll simulate a payment process
        response.message("Your ad is pending payment. Once the payment is completed, your ad will be live!")

    else:
        response.message("Thank you for your submission. We are processing your ad.")
        # TODO: Upload to social media or website here
        # After processing, reset the session
        session["state"] = "INIT"
        session.pop("image", None)
        session.pop("description", None)

    # Save the updated session back to Redis
    set_session(from_number, session)
    return str(response)

if __name__ == "__main__":
    app.run(debug=True)
