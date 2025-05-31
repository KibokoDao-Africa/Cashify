import os
import requests
from flask import current_app

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
    