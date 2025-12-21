import os
import io
from typing import Optional, BinaryIO, List
from datetime import timedelta
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.config import get_settings


class StorageService:
    """
    Service for object storage operations using MinIO.
    
    Handles video, audio, and output file storage.
    """
    
    def __init__(self):
        self.settings = get_settings()
        
        # Extract region from endpoint if it's AWS S3
        # e.g., s3.us-east-2.amazonaws.com -> us-east-2
        endpoint = self.settings.minio.endpoint
        region = None
        if "amazonaws.com" in endpoint:
            # Parse region from endpoint like s3.us-east-2.amazonaws.com
            parts = endpoint.split(".")
            if len(parts) >= 3 and parts[0] == "s3":
                region = parts[1]
                print(f"🔧 Detected AWS S3 region: {region}", flush=True)
        
        self.client = Minio(
            self.settings.minio.endpoint,
            access_key=self.settings.minio.access_key,
            secret_key=self.settings.minio.secret_key,
            secure=self.settings.minio.secure,
            region=region  # Required for AWS S3
        )
        
        # Public endpoint for direct URLs (output bucket is public)
        self.public_endpoint = os.environ.get("MINIO_PUBLIC_ENDPOINT", "localhost:9000")
    
    def ensure_buckets(self):
        """Create required buckets if they don't exist and set policies."""
        import json
        
        buckets = [
            self.settings.minio.bucket_videos,
            self.settings.minio.bucket_audio,
            self.settings.minio.bucket_output
        ]
        
        # Debug: Print connection info (without secrets)
        print(f"🔧 S3 Config: endpoint={self.settings.minio.endpoint}, secure={self.settings.minio.secure}", flush=True)
        print(f"🔧 S3 Buckets: {buckets}", flush=True)
        
        try:
            # De-duplicate buckets (all three might be the same bucket)
            unique_buckets = list(set(buckets))
            
            for bucket in unique_buckets:
                print(f"🔍 Checking bucket: {bucket}", flush=True)
                try:
                    # Try to list objects with max_keys=1 to check if bucket exists and is accessible
                    # This only requires s3:ListBucket permission on the specific bucket
                    # Unlike bucket_exists() which calls ListBuckets (requires s3:ListAllMyBuckets)
                    try:
                        objects = list(self.client.list_objects(bucket, max_keys=1))
                        print(f"✅ Bucket accessible: {bucket}", flush=True)
                    except S3Error as list_err:
                        if list_err.code == "NoSuchBucket":
                            print(f"📦 Creating bucket: {bucket}", flush=True)
                            self.client.make_bucket(bucket)
                            print(f"✅ Created bucket: {bucket}", flush=True)
                        else:
                            raise
                except S3Error as bucket_err:
                    print(f"❌ S3 Error for bucket {bucket}: code={bucket_err.code}, message={bucket_err.message}", flush=True)
                    raise

            # Ensure output bucket is publicly readable for video playback
            output_bucket = self.settings.minio.bucket_output
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{output_bucket}/*"],
                    }
                ],
            }
            try:
                self.client.set_bucket_policy(output_bucket, json.dumps(policy))
                print(f"✅ Set public read policy on {output_bucket}", flush=True)
            except Exception as e:
                print(f"⚠️ Could not set output bucket policy (may already exist): {e}", flush=True)

            print("✅ Storage initialization complete!", flush=True)
            return True
        except Exception as e:
            # In production (Railway), MinIO may not be configured yet. Don't crash the whole app;
            # instead start up and report storage as unhealthy.
            print(f"⚠️ Storage initialization failed (MinIO/S3 unreachable?): {e}", flush=True)
            return False
    
    def upload_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file to storage.
        
        Args:
            bucket: Target bucket name
            object_name: Name/path for the object in storage
            file_path: Local file path to upload
            content_type: Optional MIME type
            
        Returns:
            Object name in storage
        """
        if content_type is None:
            content_type = self._guess_content_type(file_path)
        
        self.client.fput_object(
            bucket,
            object_name,
            file_path,
            content_type=content_type
        )
        
        return object_name
    
    def upload_stream(
        self,
        bucket: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        Upload data from a stream.
        
        Args:
            bucket: Target bucket name
            object_name: Name/path for the object
            data: Binary stream to upload
            length: Length of the data
            content_type: MIME type
            
        Returns:
            Object name in storage
        """
        self.client.put_object(
            bucket,
            object_name,
            data,
            length,
            content_type=content_type
        )
        
        return object_name
    
    def download_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str
    ) -> str:
        """
        Download a file from storage.
        
        Args:
            bucket: Source bucket name
            object_name: Object name in storage
            file_path: Local path to save the file
            
        Returns:
            Local file path
        """
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        self.client.fget_object(bucket, object_name, file_path)
        
        return file_path
    
    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires: int = 3600
    ) -> str:
        """
        Get a presigned URL for temporary access to an object.
        
        Generates URL using internal client, then replaces hostname
        with public endpoint so URLs work from the browser.
        
        Args:
            bucket: Bucket name
            object_name: Object name
            expires: URL validity in seconds (default 1 hour)
            
        Returns:
            Presigned URL string
        """
        # Generate presigned URL with internal hostname
        url = self.client.presigned_get_object(
            bucket,
            object_name,
            expires=timedelta(seconds=expires)
        )
        
        # Replace internal Docker hostname with public endpoint
        # e.g., http://minio:9000/... -> http://localhost:9000/...
        internal_endpoint = self.settings.minio.endpoint
        url = url.replace(f"http://{internal_endpoint}", f"http://{self.public_endpoint}")
        url = url.replace(f"https://{internal_endpoint}", f"https://{self.public_endpoint}")
        
        return url
    
    def delete_object(self, bucket: str, object_name: str):
        """
        Delete an object from storage.
        
        Args:
            bucket: Bucket name
            object_name: Object to delete
        """
        self.client.remove_object(bucket, object_name)
    
    def delete_objects(self, bucket: str, object_names: List[str]):
        """
        Delete multiple objects from storage.
        
        Args:
            bucket: Bucket name
            object_names: List of objects to delete
        """
        from minio.deleteobjects import DeleteObject
        
        delete_list = [DeleteObject(name) for name in object_names]
        errors = self.client.remove_objects(bucket, delete_list)
        
        for error in errors:
            print(f"Delete error: {error}")
    
    def list_objects(
        self,
        bucket: str,
        prefix: Optional[str] = None,
        recursive: bool = True
    ) -> List[dict]:
        """
        List objects in a bucket.
        
        Args:
            bucket: Bucket name
            prefix: Optional prefix filter
            recursive: Whether to list recursively
            
        Returns:
            List of object info dicts
        """
        objects = self.client.list_objects(
            bucket,
            prefix=prefix,
            recursive=recursive
        )
        
        return [
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified,
                "etag": obj.etag
            }
            for obj in objects
        ]
    
    def object_exists(self, bucket: str, object_name: str) -> bool:
        """
        Check if an object exists in storage.
        
        Args:
            bucket: Bucket name
            object_name: Object name
            
        Returns:
            True if object exists
        """
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False
    
    def get_object_info(self, bucket: str, object_name: str) -> Optional[dict]:
        """
        Get metadata about an object.
        
        Args:
            bucket: Bucket name
            object_name: Object name
            
        Returns:
            Object info dict or None if not found
        """
        try:
            stat = self.client.stat_object(bucket, object_name)
            return {
                "name": stat.object_name,
                "size": stat.size,
                "last_modified": stat.last_modified,
                "etag": stat.etag,
                "content_type": stat.content_type
            }
        except S3Error:
            return None
    
    def _guess_content_type(self, file_path: str) -> str:
        """Guess content type from file extension."""
        ext = Path(file_path).suffix.lower()
        
        content_types = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".json": "application/json"
        }
        
        return content_types.get(ext, "application/octet-stream")
    
    # Convenience methods for specific buckets
    
    def upload_video(self, object_name: str, file_path: str) -> str:
        """Upload a video to the videos bucket."""
        return self.upload_file(
            self.settings.minio.bucket_videos,
            object_name,
            file_path
        )
    
    def upload_audio(self, object_name: str, file_path: str) -> str:
        """Upload audio to the audio bucket."""
        return self.upload_file(
            self.settings.minio.bucket_audio,
            object_name,
            file_path
        )
    
    def upload_output(self, object_name: str, file_path: str) -> str:
        """Upload final output to the output bucket."""
        return self.upload_file(
            self.settings.minio.bucket_output,
            object_name,
            file_path
        )
    
    def get_video_url(self, object_name: str, expires: int = 3600) -> str:
        """Get presigned URL for a video."""
        return self.get_presigned_url(
            self.settings.minio.bucket_videos,
            object_name,
            expires
        )
    
    def get_audio_url(self, object_name: str, expires: int = 3600) -> str:
        """Get presigned URL for audio."""
        return self.get_presigned_url(
            self.settings.minio.bucket_audio,
            object_name,
            expires
        )
    
    def get_output_url(self, object_name: str, expires: int = 3600) -> str:
        """Get presigned URL for output."""
        return self.get_presigned_url(
            self.settings.minio.bucket_output,
            object_name,
            expires
        )
    
    def download_video(self, object_name: str, file_path: str) -> str:
        """Download a video from storage."""
        return self.download_file(
            self.settings.minio.bucket_videos,
            object_name,
            file_path
        )
    
    # Script file methods (stored alongside videos)
    
    def upload_script(self, object_name: str, content: bytes) -> str:
        """
        Upload a narration script to storage.
        
        Scripts are stored in the videos bucket alongside their video files.
        
        Args:
            object_name: Name/path for the script (e.g., "job_id/script.txt")
            content: Script content as bytes
            
        Returns:
            Object name in storage
        """
        data = io.BytesIO(content)
        return self.upload_stream(
            self.settings.minio.bucket_videos,
            object_name,
            data,
            len(content),
            content_type="text/plain"
        )
    
    def download_script(self, object_name: str) -> Optional[str]:
        """
        Download a narration script from storage.
        
        Args:
            object_name: Script object name (e.g., "job_id/script.txt")
            
        Returns:
            Script content as string, or None if not found
        """
        try:
            response = self.client.get_object(
                self.settings.minio.bucket_videos,
                object_name
            )
            content = response.read().decode('utf-8')
            response.close()
            response.release_conn()
            return content
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise
    
    def script_exists(self, object_name: str) -> bool:
        """
        Check if a script exists in storage.
        
        Args:
            object_name: Script object name
            
        Returns:
            True if script exists
        """
        return self.object_exists(self.settings.minio.bucket_videos, object_name)
    
    def delete_script(self, object_name: str):
        """
        Delete a script from storage.
        
        Args:
            object_name: Script object name
        """
        self.delete_object(self.settings.minio.bucket_videos, object_name)

