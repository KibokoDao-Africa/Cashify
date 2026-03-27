import base64
import os
import requests
import time
import africastalking


def setup_pesapal_callback():
    """
    Run this only once to get your IPN ID
    """
    token = get_pesapal_token()
    api_url = "https://pay.pesapal.com/v3/api/URLSetup/RegisterIPN"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "url": f"{os.getenv('BASE_URL')}/pesapal-callback",
        "ipn_notification_type": "GET"
    }
    
    response = requests.post(api_url, json=payload, headers=headers)
    print(f"IPN ID: {response.json()['ipn_id']}")  # Then add this to the .env file

def get_pesapal_token():
    """
    Get OAuth token from Pesapal API
    """
    consumer_key = os.getenv('PESAPAL_CONSUMER_KEY')
    consumer_secret = os.getenv('PESAPAL_CONSUMER_SECRET')
    
    # Pesapal sandbox URL - change to production URL when going live
    api_url = "https://pay.pesapal.com/v3/api/Auth/RequestToken"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload = {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret
    }
    
    response = requests.post(api_url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()['token']
    else:
        raise Exception(f"Failed to get Pesapal token: {response.text}")

def format_phone_number(from_number):
    """
    Format phone number for payment APIs
    """
    # Strip "whatsapp:" prefix and any non-digit characters
    clean_phone = ''.join(filter(str.isdigit, from_number.replace("whatsapp:", "")))
    
    # Ensure phone number is in correct format
    if clean_phone.startswith('254'):
        return f"+{clean_phone}"
    elif clean_phone.startswith('0'):
        # Convert 07... to +2547...
        return f"+254{clean_phone[1:]}"
    else:
        return f"+{clean_phone}"

def initiate_pesapal_payment(amount, phone_number, tx_desc):
    """
    Initiate Pesapal payment request
    """
    token = get_pesapal_token()
    phone_number = format_phone_number(phone_number)
    api_url = "https://pay.pesapal.com/v3/api/Transactions/SubmitOrderRequest"
    
    # Generate unique order ID
    order_id = f"CASHIFY_{int(time.time())}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Use a generic email - Pesapal doesn't validate it
    payload = {
        "id": order_id,
        "currency": "KES",
        "amount": float(amount),
        "description": tx_desc,
        "callback_url": f"{os.getenv('BASE_URL')}/pesapal-callback",
        "redirect_mode": "PARENT_WINDOW",
        "notification_id": os.getenv('PESAPAL_IPN_ID'),
        "branch": "Cashify",
        "billing_address": {
            "email_address": "customer@cashify.app",  # Generic email - not validated
            "phone_number": phone_number,
            "country_code": "KE",
            "first_name": "Customer",
            "middle_name": "",
            "last_name": "Cashify",
            "line_1": "Nairobi",
            "line_2": "",
            "city": "Nairobi",
            "state": "Nairobi",
            "postal_code": "00100",
            "zip_code": "00100"
        }
    }
    
    response = requests.post(api_url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()  # Includes a payment URL that user can visit to complete payment
    else:
        raise Exception(f"Payment initiation failed: {response.text}")
    
def check_pesapal_payment_status(order_tracking_id):
    """
    Check payment status with Pesapal
    """
    token = get_pesapal_token()
    api_url = f"https://pay.pesapal.com/v3/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(api_url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to check payment status: {response.text}")

def init_africastalking():
    """
    Initialize Africa's Talking SDK
    """
    username = os.getenv('AT_USERNAME')
    api_key = os.getenv('AT_API_KEY')
    africastalking.initialize(username, api_key)
    return africastalking.Payment

def send_money_via_at(phone_number, amount, description="Cashify payout"):
    """
    B2C using Africa's Talking
    """
    try:
        phone_number = format_phone_number(phone_number)
        
        # Initialize AT
        payment = init_africastalking()
        
        result = payment.mobile_checkout(
            product_name="Cashify",
            phone_number=phone_number,
            currency_code="KES",
            amount=float(amount),
            metadata={
                "description": description,
                "reference": f"CASHIFY_PAYOUT_{int(time.time())}"
            }
        )
        
        return {
            "status": "success",
            "data": result,
            "message": "Payout initiated via Africa's Talking"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Africa's Talking payout failed: {str(e)}"
        }

def check_at_transaction_status(transaction_id=None):
    """
    Check Africa's Talking transaction status
    """
    try:
        payment = init_africastalking()
        
        # Get recent transactions
        result = payment.fetch_product_transactions(
            product_name="Cashify"
        )
        
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Status check failed: {str(e)}"
        }

def get_at_wallet_balance():
    """
    Check Africa's Talking wallet balance
    """
    try:
        payment = init_africastalking()
        
        result = payment.fetch_wallet_balance()
        
        return {
            "status": "success",
            "balance": result,
            "message": "Balance retrieved successfully"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Balance check failed: {str(e)}"
        }
