import base64
import os
import requests
import time
from requests.auth import HTTPBasicAuth
from flask import current_app

def get_mpesa_token():
    """
    Get OAuth token from M-pesa API
    """
    consumer_key = os.getenv('MPESA_CONSUMER_KEY')
    consumer_secret = os.getenv('MPESA_CONSUMER_SECRET')
    api_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    # make a get request using python requests library
    r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret))

    # return access_token from response
    return r.json()['access_token']

def lipa_na_mpesa(amount, phone_number, tx_desc):
    """
    Initiate Lipa Na M-Pesa payment request
    """
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
    response = requests.post(api_url, json=request, headers=headers)
    response = response.json()

    if 'errorMessage' in response:   # fail
        raise Exception(response['errorMessage'])
    
    elif 'ResponseCode' in response and response['ResponseCode'] == '0':   # success
        return response['ResponseDescription']

def format_phone_for_mpesa(from_number):
    """
    Format phone number for M-Pesa API
    """
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
    
    return mpesa_phone

def initiate_payment(from_number, amount, description):
    """
    Helper function to initiate payment from the main app
    """
    try:
        mpesa_phone = format_phone_for_mpesa(from_number)
        result = lipa_na_mpesa(amount, mpesa_phone, description)
        return True, result
    except Exception as e:
        current_app.logger.error(f"Payment initiation error: {str(e)}")
        return False, str(e)