"""Eskiz SMS service for Uzbekistan"""

import requests
import logging
import time
from typing import Tuple, Optional, Dict, Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class EskizConfig:
    """Eskiz API configuration and constants"""
    
    BASE_URL = "https://api.eskiz.uz"
    LOGIN_ENDPOINT = "/api/auth/login"
    SEND_SMS_ENDPOINT = "/api/message/sms/send"
    
    TOKEN_CACHE_KEY = "eskiz_auth_token"
    TOKEN_CACHE_TTL = 29 * 60  # Token valid 30 min, cache for 29 min
    REQUEST_TIMEOUT = 10
    
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    RATE_LIMIT_CACHE_PREFIX = "eskiz_rate_limit:"
    RATE_LIMIT_WINDOW = 60  # Prevent duplicate SMS within 60s
    
    @staticmethod
    def validate_phone(phone: str) -> str:
        """
        Validate and normalize phone to +998 format.
        
        Supports: +998..., 998..., 90..., 0..., with various separators
        
        Args:
            phone: Phone number in various formats
            
        Returns:
            Normalized phone number (+998...)
            
        Raises:
            ValueError: If phone format is invalid
        """
        if not phone or not isinstance(phone, str):
            raise ValueError("Phone must be a non-empty string")
        
        cleaned = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        if cleaned.startswith('+998'):
            if len(cleaned) != 13:
                raise ValueError(f"Invalid phone length: {cleaned}")
            return cleaned
        
        if cleaned.startswith('998'):
            if len(cleaned) != 12:
                raise ValueError(f"Invalid phone length: {cleaned}")
            return '+' + cleaned
        
        if cleaned[0] in ('9',) and len(cleaned) >= 9:
            if len(cleaned) == 9:
                return '+998' + cleaned
            elif len(cleaned) == 11:
                return '+' + cleaned
        
        if cleaned.startswith('0') and len(cleaned) == 10:
            return '+998' + cleaned[1:]
        
        raise ValueError(f"Invalid phone format: {phone}")


class EskizAuthManager:
    """Manages Eskiz API authentication and token caching"""
    
    def __init__(self, email: str = None, password: str = None):
        self.email = email or settings.ESKIZ_EMAIL
        self.password = password or settings.ESKIZ_PASSWORD
        
        if not self.email or not self.password:
            raise ValueError("ESKIZ_EMAIL and ESKIZ_PASSWORD must be set")
    
    def get_token(self) -> Optional[str]:
        """
        Get valid API token (cached or fresh).
        
        Returns:
            Valid API token
            
        Raises:
            EskizAuthError: If login fails
        """
        cached_token = cache.get(EskizConfig.TOKEN_CACHE_KEY)
        if cached_token:
            logger.debug("Using cached Eskiz token")
            return cached_token
        
        return self._login()
    
    def _login(self) -> str:
        """
        Authenticate with Eskiz API.
        
        Returns:
            API token
            
        Raises:
            EskizAuthError: If authentication fails
        """
        try:
            url = f"{EskizConfig.BASE_URL}{EskizConfig.LOGIN_ENDPOINT}"
            payload = {"email": self.email, "password": self.password}
            
            logger.info("Authenticating with Eskiz API")
            response = requests.post(
                url,
                json=payload,
                timeout=EskizConfig.REQUEST_TIMEOUT
            )
            
            if response.status_code != 200:
                data = response.json() if response.headers.get('content-type') == 'application/json' else {}
                msg = data.get('message', f"HTTP {response.status_code}")
                logger.error(f"Eskiz login failed: {msg}")
                raise EskizAuthError(f"Authentication failed: {msg}", response.status_code)
            
            data = response.json()
            token = data.get('token')
            
            if not token:
                logger.error("Eskiz login response missing token")
                raise EskizAuthError("No token in response")
            
            cache.set(EskizConfig.TOKEN_CACHE_KEY, token, timeout=EskizConfig.TOKEN_CACHE_TTL)
            logger.info("Successfully authenticated with Eskiz")
            return token
        
        except requests.exceptions.Timeout:
            logger.error("Eskiz login timeout")
            raise EskizAuthError("Request timeout during authentication")
        except requests.exceptions.ConnectionError:
            logger.error("Eskiz login connection error")
            raise EskizAuthError("Connection error during authentication")
        except EskizAuthError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Eskiz login: {e}")
            raise EskizAuthError(f"Unexpected error: {str(e)}")
    
    def invalidate_cache(self):
        """Invalidate cached token."""
        cache.delete(EskizConfig.TOKEN_CACHE_KEY)
        logger.info("Invalidated cached Eskiz token")


class EskizSMSClient:
    """Sends SMS via Eskiz API with retry logic and rate limiting"""
    
    def __init__(self, auth_manager: EskizAuthManager = None):
        self.auth = auth_manager or EskizAuthManager()
    
    def send_sms(self, phone: str, message: str) -> Dict[str, Any]:
        """
        Send SMS via Eskiz API.
        
        Args:
            phone: Recipient phone number
            message: SMS message content
            
        Returns:
            Dict with success, message_id, status, and error fields
        """
        try:
            normalized_phone = EskizConfig.validate_phone(phone)
        except ValueError as e:
            logger.error(f"Invalid phone number {phone}: {e}")
            return self._error_response('invalid_phone', str(e))
        
        if not message or not isinstance(message, str):
            logger.error(f"Invalid message: {message}")
            return self._error_response('invalid_message', "Message must be non-empty string")
        
        if len(message) > 160:
            logger.warning(f"Message exceeds 160 chars ({len(message)})")
        
        # Check rate limiting
        rate_limit_key = f"{EskizConfig.RATE_LIMIT_CACHE_PREFIX}{normalized_phone}"
        if cache.get(rate_limit_key):
            logger.warning(f"Rate limit: SMS to {normalized_phone} within 60 seconds")
            return self._error_response('rate_limited', "SMS already sent recently")
        
        # Send with retries
        return self._send_with_retry(normalized_phone, message, rate_limit_key)
    
    def _send_with_retry(self, phone: str, message: str, rate_limit_key: str) -> Dict[str, Any]:
        """Attempt to send SMS with retry logic"""
        for attempt in range(1, EskizConfig.MAX_RETRIES + 1):
            try:
                token = self.auth.get_token()
                
                url = f"{EskizConfig.BASE_URL}{EskizConfig.SEND_SMS_ENDPOINT}"
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                payload = {
                    'mobile_phone': phone,
                    'message': message,
                    'from': getattr(settings, 'ESKIZ_FROM_ID', '4546')
                }
                
                logger.info(f"Sending SMS to {phone} (attempt {attempt}/{EskizConfig.MAX_RETRIES})")
                
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=EskizConfig.REQUEST_TIMEOUT
                )
                
                if response.status_code == 200:
                    data = response.json()
                    message_id = data.get('id')
                    status = data.get('status')
                    
                    cache.set(rate_limit_key, True, timeout=EskizConfig.RATE_LIMIT_WINDOW)
                    logger.info(f"SMS sent: phone={phone}, message_id={message_id}")
                    
                    return {
                        'success': True,
                        'message_id': message_id,
                        'status': status,
                        'error': None
                    }
                
                elif response.status_code == 401:
                    msg = self._get_error_message(response)
                    logger.warning(f"SMS unauthorized (attempt {attempt}): {msg}")
                    self.auth.invalidate_cache()
                    if attempt < EskizConfig.MAX_RETRIES:
                        time.sleep(EskizConfig.RETRY_DELAY)
                        continue
                    return self._error_response('failed', msg)
                
                else:
                    msg = self._get_error_message(response)
                    logger.error(f"SMS request failed: {msg}")
                    if response.status_code >= 500 and attempt < EskizConfig.MAX_RETRIES:
                        time.sleep(EskizConfig.RETRY_DELAY)
                        continue
                    return self._error_response('failed', msg)
            
            except requests.exceptions.Timeout:
                logger.error(f"SMS timeout (attempt {attempt}/{EskizConfig.MAX_RETRIES})")
                if attempt < EskizConfig.MAX_RETRIES:
                    time.sleep(EskizConfig.RETRY_DELAY)
                    continue
                return self._error_response('failed', "Request timeout")
            
            except requests.exceptions.ConnectionError:
                logger.error(f"SMS connection error (attempt {attempt}/{EskizConfig.MAX_RETRIES})")
                if attempt < EskizConfig.MAX_RETRIES:
                    time.sleep(EskizConfig.RETRY_DELAY)
                    continue
                return self._error_response('failed', "Connection error")
            
            except Exception as e:
                logger.error(f"Unexpected error sending SMS (attempt {attempt}): {e}")
                return self._error_response('failed', str(e))
        
        return self._error_response('failed', "Max retries exceeded")
    
    @staticmethod
    def _get_error_message(response) -> str:
        """Extract error message from response"""
        try:
            if response.headers.get('content-type') == 'application/json':
                data = response.json()
                return data.get('message', f"HTTP {response.status_code}")
        except Exception:
            pass
        return f"HTTP {response.status_code}"
    
    @staticmethod
    def _error_response(status: str, error: str) -> Dict[str, Any]:
        """Create error response dict"""
        return {
            'success': False,
            'message_id': None,
            'status': status,
            'error': error
        }


class EskizSMSService:
    """High-level SMS service with singleton pattern"""
    
    _instance = None
    _auth_manager = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._auth_manager = EskizAuthManager()
            cls._client = EskizSMSClient(auth_manager=cls._auth_manager)
        return cls._instance
    
    def send_sms(self, phone: str, message: str) -> Tuple[bool, str, Optional[str]]:
        """
        Send SMS to recipient.
        
        Args:
            phone: Phone number
            message: SMS message
            
        Returns:
            Tuple of (success, message, message_id)
        """
        result = self._client.send_sms(phone, message)
        
        if result['success']:
            return (True, result['status'], result['message_id'])
        else:
            return (False, result['error'], None)


class EskizError(Exception):
    """Base exception for Eskiz service errors"""
    pass


class EskizAuthError(EskizError):
    """Authentication/token error"""
    
    def __init__(self, message, status_code=None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class EskizSMSError(EskizError):
    """SMS sending error"""
    pass


def send_sms(phone: str, message: str) -> bool:
    """
    Send SMS via Eskiz.
    
    Args:
        phone: Recipient phone number
        message: Message content
        
    Returns:
        Boolean indicating success
    """
    try:
        service = EskizSMSService()
        success, msg, msg_id = service.send_sms(phone, message)
        
        if not success:
            logger.warning(f"Failed to send SMS to {phone}: {msg}")
        
        return success
    except Exception as e:
        logger.error(f"Unexpected error in send_sms: {e}", exc_info=True)
        return False
