import os
import requests
from twilio.rest import Client
from flask import current_app

class TemplateManager:
    def __init__(self):
        self.client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.content_sid_cache = {}

    def get_or_create_list_template(self, template_name, body, items):
        if template_name in self.content_sid_cache:
            return self.content_sid_cache[template_name]

        try:
            templates = self.client.content.v1.contents.list()
            for template in templates:
                if hasattr(template, 'friendly_name') and template.friendly_name == template_name:
                    content_sid = template.sid
                    self.content_sid_cache[template_name] = content_sid
                    return content_sid

            list_items = [
                {
                    "id": item["id"],
                    "item": item["title"],
                    "description": item.get("description", "")
                }
                for item in items
            ]

            payload = {
                "friendly_name": template_name,
                "language": "en",
                "variables": {"1": "Customer"},
                "types": {
                    "twilio/list-picker": {
                        "body": body,
                        "button": "Choose an option",
                        "items": list_items
                    },
                    "twilio/text": {
                        "body": body
                    }
                }
            }

            response = requests.post(
                "https://content.twilio.com/v1/Content",
                auth=(self.account_sid, self.auth_token),
                headers={"Content-Type": "application/json"},
                json=payload
            )
            response.raise_for_status()
            content_sid = response.json()["sid"]
            self.content_sid_cache[template_name] = content_sid
            current_app.logger.info(f"Created list template: {template_name} with SID: {content_sid}")
            return content_sid

        except Exception as e:
            current_app.logger.error(f"Error creating list template {template_name}: {str(e)}")
            return None

    def get_or_create_button_template(self, template_name, body, buttons):
        if template_name in self.content_sid_cache:
            return self.content_sid_cache[template_name]

        try:
            templates = self.client.content.v1.contents.list()
            for template in templates:
                if hasattr(template, 'friendly_name') and template.friendly_name == template_name:
                    content_sid = template.sid
                    self.content_sid_cache[template_name] = content_sid
                    return content_sid

            button_items = [
                {
                    "id": button["id"],
                    "title": button["title"]
                }
                for button in buttons
            ]

            payload = {
                "friendly_name": template_name,
                "language": "en",
                "variables": {"1": "Customer"},
                "types": {
                    "twilio/quick-reply": {
                        "body": body,
                        "actions": button_items
                    },
                    "twilio/text": {
                        "body": body
                    }
                }
            }

            response = requests.post(
                "https://content.twilio.com/v1/Content",
                auth=(self.account_sid, self.auth_token),
                headers={"Content-Type": "application/json"},
                json=payload
            )
            response.raise_for_status()
            content_sid = response.json()["sid"]
            self.content_sid_cache[template_name] = content_sid
            current_app.logger.info(f"Created button template: {template_name} with SID: {content_sid}")
            return content_sid

        except Exception as e:
            current_app.logger.error(f"Error creating button template {template_name}: {str(e)}")
            return None

    def send_interactive_message(self, to_number, content_sid, variables=None):
        try:
            from_number = os.getenv('TWILIO_WHATSAPP_NUMBER')
            if not from_number.startswith('whatsapp:'):
                from_number = f"whatsapp:{from_number}"

            message_params = {
                'content_sid': content_sid,
                'from_': from_number,
                'to': to_number
            }

            if variables:
                message_params['content_variables'] = variables

            message = self.client.messages.create(**message_params)
            current_app.logger.info(f"Sent interactive message using template {content_sid} to {to_number} with SID: {message.sid}")
            return message.sid

        except Exception as e:
            current_app.logger.error(f"Error sending interactive message: {str(e)}")
            return None

# Global instance
template_manager = TemplateManager()
