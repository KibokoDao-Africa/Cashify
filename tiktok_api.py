import os
import requests
from moviepy.editor import ImageSequenceClip


def upload_to_tiktok(media_urls=None, is_video=False, caption=""):
    """
    Upload media to TikTok account. Converts images to video if needed.
    
    Args:
        media_urls (list): List of URLs to the images/video
        is_video (bool): Whether the media is video (if True, only one video allowed)
        caption (str): The caption for the post
        
    Returns:
        str: URL to the TikTok video post
    """
    try:
        media_urls = media_urls or []
        if not media_urls:
            raise ValueError("No media URLs provided")

        # Load credentials from environment
        access_token = os.getenv("TIKTOK_ACCESS_TOKEN")
        client_key = os.getenv("TIKTOK_CLIENT_KEY")
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
        username = os.getenv("TIKTOK_USERNAME")

        if not all([access_token, client_key, client_secret, username]):
            raise EnvironmentError("Missing one or more TikTok credentials in environment variables")

        # Handle video upload
        if is_video:
            if len(media_urls) > 1:
                raise ValueError("Multiple videos are not supported. Please provide only one video URL.")
            
            video_url = media_urls[0]
            video_response = requests.get(video_url)
            if video_response.status_code != 200:
                raise Exception("Failed to download video from provided URL")

            video_path = "/tmp/tiktok_upload.mp4"
            with open(video_path, "wb") as f:
                f.write(video_response.content)

        # Handle image-to-video conversion
        else:
            image_paths = []
            for i, img_url in enumerate(media_urls):
                img_response = requests.get(img_url)
                if img_response.status_code != 200:
                    raise Exception(f"Failed to download image: {img_url}")
                img_path = f"/tmp/image_{i}.jpg"
                with open(img_path, "wb") as f:
                    f.write(img_response.content)
                image_paths.append(img_path)

            # Convert images to video
            clip = ImageSequenceClip(image_paths, fps=1/5)  # 1 image every 5 seconds
            video_path = "/tmp/tiktok_upload.mp4"
            clip.write_videofile(video_path, codec='libx264')

        # Step 1: Initialize upload
        init_url = "https://open.tiktokapis.com/v2/video/upload/init/"
        headers = {"Authorization": f"Bearer {access_token}"}
        init_response = requests.post(init_url, headers=headers)
        upload_url = init_response.json().get("upload_url")
        if not upload_url:
            raise Exception("Failed to get TikTok upload URL")

        # Step 2: Upload video file
        with open(video_path, "rb") as video_file:
            upload_response = requests.put(upload_url, data=video_file)
        video_id = upload_response.json().get("video_id")
        if not video_id:
            raise Exception("Failed to upload video to TikTok")

        # Step 3: Publish video
        publish_url = "https://open.tiktokapis.com/v2/video/publish/"
        headers.update({"Content-Type": "application/json"})
        payload = {
            "video_id": video_id,
            "title": caption,
            "description": caption,
            "visibility": "public"
        }
        publish_response = requests.post(publish_url, headers=headers, json=payload)
        result = publish_response.json()

        if "id" in result:
            return f"https://www.tiktok.com/@{username}/video/{result['id']}"
        else:
            raise Exception(f"Failed to post to TikTok: {result.get('error', {}).get('message', 'Unknown error')}")

    except Exception as e:
        raise e
