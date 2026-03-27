import os
import requests
from moviepy import ImageSequenceClip

def refresh_access_token():
    """Refresh TikTok user access token using stored refresh token."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    refresh_token = os.getenv("TIKTOK_REFRESH_TOKEN")

    if not all([client_key, client_secret, refresh_token]):
        raise EnvironmentError("Missing TikTok credentials or refresh token")

    url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    response = requests.post(url, headers=headers, data=data)
    tokens = response.json()
    if tokens.get("error", {}).get("code") != "ok":
        raise Exception(f"Failed to refresh token: {tokens['error']['message']}")

    return tokens["access_token"]

def make_tiktok_request(url, headers, payload=None, method="POST", retry=True):
    """Make a TikTok API request with auto-refresh on token failure."""
    response = requests.request(method, url, headers=headers, json=payload)
    result = response.json()

    if result.get("error", {}).get("code") == "access_token_invalid" and retry:
        new_token = refresh_access_token()
        headers["Authorization"] = f"Bearer {new_token}"
        response = requests.request(method, url, headers=headers, json=payload)
        result = response.json()

    return result

def upload_to_tiktok(media_urls=None, is_video=False, caption=""):
    try:
        media_urls = media_urls or []
        if not media_urls:
            raise ValueError("No media URLs provided")

        access_token = os.getenv("TIKTOK_ACCESS_TOKEN")
        if not access_token:
            access_token = refresh_access_token()

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
        init_response = make_tiktok_request(init_url, init_headers, init_payload)
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
        publish_response = make_tiktok_request(publish_url, publish_headers, publish_payload)
        
        if publish_response["error"]["code"] == "ok":
            return publish_response["data"]["video_url"]
        else:
            raise Exception(f"Failed to publish video: {publish_response['error']['message']}")

    except Exception as e:
        raise RuntimeError(f"TikTok upload failed: {e}")
