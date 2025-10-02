import os
import requests

def upload_to_facebook(media_urls=None, is_video=False, caption=""):
    """
    Upload media to Facebook page
    
    Args:
        media_urls (list): List of URLs to media files
        is_video (bool): Whether the media is video (if True, only single video allowed)
        caption (str): The caption for the post
        
    Returns:
        str: URL to the Facebook post
    """
    try:
        media_urls = media_urls or []
        
        if not media_urls:
            raise ValueError("No media URLs provided")
        
        # If it's video, validate only one URL is provided
        if is_video and len(media_urls) > 1:
            raise ValueError("Multiple videos are not supported. Please provide only one video URL.")
        
        # Single media item
        if len(media_urls) == 1:
            if is_video:
                facebook_url = f"https://graph.facebook.com/v19.0/{os.getenv('FACEBOOK_PAGE_ID')}/videos"
                facebook_params = {
                    "access_token": os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN'),
                    "file_url": media_urls[0],
                    "description": caption,
                    "published": "true"
                }
            else:
                facebook_url = f"https://graph.facebook.com/v19.0/{os.getenv('FACEBOOK_PAGE_ID')}/photos"
                facebook_params = {
                    "access_token": os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN'),
                    "url": media_urls[0],
                    "caption": caption,
                    "published": "true"
                }
            
            response = requests.post(facebook_url, data=facebook_params)
            result = response.json()
            
            if 'id' in result:
                if is_video:
                    return f"https://www.facebook.com/watch?v={result['id']}"
                else:
                    return f"https://www.facebook.com/photo?fbid={result['id']}"
            else:
                raise Exception(f"Failed to post to Facebook: {result.get('error', {}).get('message', 'Unknown error')}")
        
        # Multiple images (carousel) - only allowed for images
        else:
            if is_video:
                raise ValueError("Multiple videos are not supported. Please provide only one video URL.")
            
            # Create image carousel
            attached_media = []
            
            for img_url in media_urls:
                upload_url = f"https://graph.facebook.com/v19.0/{os.getenv('FACEBOOK_PAGE_ID')}/photos"
                upload_params = {
                    "access_token": os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN'),
                    "url": img_url,
                    "published": "false"  # Upload but don't publish yet
                }
                
                upload_response = requests.post(upload_url, data=upload_params)
                upload_result = upload_response.json()
                
                if 'id' in upload_result:
                    attached_media.append({"media_fbid": upload_result['id']})
                else:
                    raise Exception(f"Failed to upload image to Facebook: {upload_result.get('error', {}).get('message', 'Unknown error')}")
            
            # Create the carousel post
            post_url = f"https://graph.facebook.com/v19.0/{os.getenv('FACEBOOK_PAGE_ID')}/feed"
            post_params = {
                "access_token": os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN'),
                "message": caption,
                "attached_media": attached_media
            }
            
            response = requests.post(post_url, json=post_params)
            result = response.json()
            
            if 'id' in result:
                return f"https://www.facebook.com/permalink.php?story_fbid={result['id'].split('_')[1]}&id={os.getenv('FACEBOOK_PAGE_ID')}"
            else:
                raise Exception(f"Failed to create carousel post on Facebook: {result.get('error', {}).get('message', 'Unknown error')}")
            
    except Exception as e:
        raise e

def upload_to_instagram(media_urls=None, is_video=False, caption="", story=False):
    """
    Upload media to Instagram feed or story
    
    Args:
        media_urls (list): List of URLs to media files
        is_video (bool): Whether the media is video
        caption (str): The caption for the post
        story (bool): Whether to post as a story instead of feed post
        
    Returns:
        str or list: Instagram post ID(s) - returns list of IDs for multiple stories
    """
    import time
    
    try:
        media_urls = media_urls or []
        
        if not media_urls:
            raise ValueError("No media URLs provided")
            
        # If posting stories, we upload each media item as a separate story
        if story:
            story_ids = []
            container_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media"
            publish_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media_publish"
            
            for media_url in media_urls:
                container_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "media_type": "STORIES",
                    "story_sticker_ids": '[{"story_sticker_type":"MENTION","story_sticker_value":"' + caption + '"}]'
                }
                
                if is_video:
                    container_params["video_url"] = media_url
                else:
                    container_params["image_url"] = media_url
                
                container_response = requests.post(container_url, data=container_params)
                container_data = container_response.json()
                
                if 'id' not in container_data:
                    media_type = "video" if is_video else "image"
                    raise Exception(f"Failed to create {media_type} story container: {container_data}")
                
                creation_id = container_data['id']
                
                # Wait for processing to complete (both video and image)
                status_url = f"https://graph.facebook.com/v19.0/{creation_id}"
                max_retries = 30  # Wait up to 5 minutes
                retry_count = 0
                
                while retry_count < max_retries:
                    status_response = requests.get(status_url, params={
                        "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                        "fields": "status_code"
                    })
                    status_data = status_response.json()
                    
                    if status_data.get('status_code') == 'FINISHED':
                        break
                    elif status_data.get('status_code') == 'ERROR':
                        raise Exception(f"Media processing failed: {status_data}")
                    
                    time.sleep(5)  # Wait 5 seconds for images, 10 for videos
                    retry_count += 1
                
                if retry_count >= max_retries:
                    media_type = "Video" if is_video else "Image"
                    raise Exception(f"{media_type} processing timeout - media is taking too long to process")
                
                # Publish the story
                publish_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "creation_id": creation_id
                }
                
                publish_response = requests.post(publish_url, data=publish_params)
                publish_data = publish_response.json()
                
                if 'id' not in publish_data:
                    media_type = "video" if is_video else "image"
                    raise Exception(f"Failed to publish {media_type} story: {publish_data}")
                
                story_ids.append(publish_data['id'])
                
            return story_ids
        
        # For feed posts
        else:
            container_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media"
            publish_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media_publish"
            
            # Single media post
            if len(media_urls) == 1:
                container_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "caption": caption,
                }
                
                if is_video:
                    container_params["media_type"] = "REELS"
                    container_params["video_url"] = media_urls[0]
                else:
                    container_params["media_type"] = "IMAGE"
                    container_params["image_url"] = media_urls[0]
                
                container_response = requests.post(container_url, data=container_params)
                container_data = container_response.json()
                
                if 'id' not in container_data:
                    raise Exception(f"Failed to create media container: {container_data}")
                
                creation_id = container_data['id']
                
                # Wait for processing to complete (both video and image)
                status_url = f"https://graph.facebook.com/v19.0/{creation_id}"
                max_retries = 30  # Wait up to 5 minutes
                retry_count = 0
                
                while retry_count < max_retries:
                    status_response = requests.get(status_url, params={
                        "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                        "fields": "status_code"
                    })
                    status_data = status_response.json()
                    
                    if status_data.get('status_code') == 'FINISHED':
                        break
                    elif status_data.get('status_code') == 'ERROR':
                        break  # Let it raise the error later in publish step
                    
                    time.sleep(5 if not is_video else 10)  # 5 seconds for images, 10 for videos
                    retry_count += 1
                
                if retry_count >= max_retries:
                    media_type = "Video" if is_video else "Image"
                    raise Exception(f"{media_type} processing timeout - media is taking too long to process")
                
                # Publish the container
                publish_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "creation_id": creation_id
                }
                
                publish_response = requests.post(publish_url, data=publish_params)
                publish_data = publish_response.json()
                
                if 'id' not in publish_data:
                    raise Exception(f"Failed to publish media: {publish_data}")
                
                return publish_data['id']
            
            # Carousel post (multiple media) - only for images
            else:
                if is_video:
                    raise ValueError("Multiple videos are not supported in carousels. Please provide only one video URL.")
                
                # Create image carousel
                carousel_url = f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/media"
                
                # First, create the child media objects
                children_ids = []
                
                for img_url in media_urls:
                    child_params = {
                        "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                        "media_type": "IMAGE",
                        "image_url": img_url,
                        "is_carousel_item": "true"
                    }
                    
                    child_response = requests.post(carousel_url, data=child_params)
                    child_data = child_response.json()
                    
                    if 'id' not in child_data:
                        raise Exception(f"Failed to create carousel image: {child_data}")
                    
                    children_ids.append(child_data['id'])
                
                # Wait for all carousel images to be processed
                for child_id in children_ids:
                    status_url = f"https://graph.facebook.com/v19.0/{child_id}"
                    max_retries = 30
                    retry_count = 0
                    
                    while retry_count < max_retries:
                        status_response = requests.get(status_url, params={
                            "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                            "fields": "status_code"
                        })
                        status_data = status_response.json()
                        
                        if status_data.get('status_code') == 'FINISHED':
                            break
                        elif status_data.get('status_code') == 'ERROR':
                            raise Exception(f"Carousel image processing failed: {status_data}")
                        
                        time.sleep(3)  # Shorter wait for carousel images
                        retry_count += 1
                    
                    if retry_count >= max_retries:
                        raise Exception("Carousel image processing timeout")
                
                # Create the carousel container with all children
                carousel_container_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "caption": caption,
                    "media_type": "CAROUSEL",
                    "children": ",".join(children_ids)
                }
                
                carousel_response = requests.post(carousel_url, data=carousel_container_params)
                carousel_data = carousel_response.json()
                
                if 'id' not in carousel_data:
                    raise Exception(f"Failed to create carousel container: {carousel_data}")
                
                creation_id = carousel_data['id']
                
                # Wait for carousel container to be ready
                status_url = f"https://graph.facebook.com/v19.0/{creation_id}"
                max_retries = 30
                retry_count = 0
                
                while retry_count < max_retries:
                    status_response = requests.get(status_url, params={
                        "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                        "fields": "status_code"
                    })
                    status_data = status_response.json()
                    
                    if status_data.get('status_code') == 'FINISHED':
                        break
                    elif status_data.get('status_code') == 'ERROR':
                        raise Exception(f"Carousel container processing failed: {status_data}")
                    
                    time.sleep(5)
                    retry_count += 1
                
                if retry_count >= max_retries:
                    raise Exception("Carousel container processing timeout")
                
                # Publish the carousel
                publish_params = {
                    "access_token": os.getenv('INSTAGRAM_ACCESS_TOKEN'),
                    "creation_id": creation_id
                }
                
                publish_response = requests.post(publish_url, data=publish_params)
                publish_data = publish_response.json()
                
                if 'id' not in publish_data:
                    raise Exception(f"Failed to publish carousel: {publish_data}")
                
                return publish_data['id']
        
    except Exception as e:
        raise e
