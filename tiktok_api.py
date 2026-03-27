import os
import requests
from moviepy import ImageSequenceClip


def get_access_token_from_auth_code(auth_code, client_id, client_secret, redirect_uri):
    """Exchange authorization code for access token"""
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    
    token_payload = {
        "client_key": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    
    token_headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    response = requests.post(token_url, headers=token_headers, data=token_payload)
    response_data = response.json()
    
    if response.status_code == 200 and "access_token" in response_data:
        return response_data["access_token"]
    else:
        raise Exception(f"Failed to get access token: {response_data}")


def upload_to_tiktok(media_urls=None, is_video=False, caption="", auth_code=None):
    try:
        media_urls = media_urls or []
        if not media_urls:
            raise ValueError("No media URLs provided")

        # Get OAuth credentials from environment
        authorization_code = auth_code or os.getenv("TIKTOK_AUTH_CODE")
        client_key = os.getenv("TIKTOK_CLIENT_KEY")
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
        redirect_uri = f"{os.getenv('BASE_URL')}/tiktok/callback"
        
        if not all([client_key, client_secret, authorization_code]):
            raise ValueError("Missing TikTok OAuth credentials in environment")
        
        # Exchange authorization code for access token
        access_token = get_access_token_from_auth_code(
            authorization_code, client_key, client_secret, redirect_uri
        )

        # Prepare video file
        video_path = "/tmp/tiktok_upload.mp4"
        if is_video:
            video_url = media_urls[0]
            video_response = requests.get(video_url)
            with open(video_path, "wb") as f:
                f.write(video_response.content)
        else:
            image_paths = []
            for i, img_url in enumerate(media_urls):
                img_response = requests.get(img_url)
                img_path = f"/tmp/image_{i}.jpg"
                with open(img_path, "wb") as f:
                    f.write(img_response.content)
                image_paths.append(img_path)
            clip = ImageSequenceClip(image_paths, fps=0.2)
            clip.write_videofile(video_path, codec='libx264')

        # Get file size and chunk info
        file_size = os.path.getsize(video_path)
        chunk_size = 5 * 1024 * 1024  # 5MB
        total_chunks = (file_size + chunk_size - 1) // chunk_size

        # Step 1: Initialize upload
        init_url = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
        init_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }
        init_payload = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks
            }
        }
        init_response = requests.request("POST", init_url, headers=init_headers, json=init_payload)
        init_response = init_response.json()
        upload_url = init_response.get("data", {}).get("upload_url")
        publish_id = init_response.get("data", {}).get("publish_id")
        if not upload_url or not publish_id:
            raise Exception("Failed to initialize TikTok upload")

        # Step 2: Upload chunks
        with open(video_path, "rb") as f:
            for i in range(total_chunks):
                chunk = f.read(chunk_size)
                chunk_headers = {
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {i*chunk_size}-{(i+1)*chunk_size-1}/{file_size}"
                }
                requests.put(upload_url, headers=chunk_headers, data=chunk)

        # Step 3: Publish video
        publish_url = "https://open.tiktokapis.com/v2/post/publish/inbox/video/publish/"
        publish_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        publish_payload = {
            "publish_id": publish_id,
            "text": caption
        }
        publish_response = requests.request("POST", publish_url, headers=publish_headers, json=publish_payload)
        publish_response = publish_response.json()
        
        if publish_response["error"]["code"] == "ok":
            return publish_response["data"]["video_url"]
        else:
            raise Exception(f"Failed to publish video: {publish_response['error']['message']}")

    except Exception as e:
        raise RuntimeError(f"TikTok upload failed: {e}")

