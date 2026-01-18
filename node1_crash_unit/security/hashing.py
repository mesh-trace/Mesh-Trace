"""
Data hashing module
Provides cryptographic hashing for data integrity verification
"""

import hashlib
import hmac
from config import HASH_ALGORITHM


def hash_data(data, algorithm=None):
    """
    Generate cryptographic hash of data
    
    Args:
        data: Data to hash (string or bytes)
        algorithm: Hash algorithm to use (default from config)
        
    Returns:
        str: Hexadecimal hash string
    """
    if algorithm is None:
        algorithm = HASH_ALGORITHM
    
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    return hash_obj.hexdigest()


def hmac_hash(data, secret_key, algorithm=None):
    """
    Generate HMAC hash for authenticated hashing
    
    Args:
        data: Data to hash (string or bytes)
        secret_key: Secret key for HMAC (string or bytes)
        algorithm: Hash algorithm to use (default from config)
        
    Returns:
        str: Hexadecimal HMAC hash string
    """
    if algorithm is None:
        algorithm = HASH_ALGORITHM
    
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    if isinstance(secret_key, str):
        secret_key = secret_key.encode('utf-8')
    
    hmac_obj = hmac.new(secret_key, data, algorithm)
    return hmac_obj.hexdigest()


def verify_hash(data, expected_hash, algorithm=None):
    """
    Verify data integrity by comparing hash
    
    Args:
        data: Data to verify (string or bytes)
        expected_hash: Expected hash value (hex string)
        algorithm: Hash algorithm to use (default from config)
        
    Returns:
        bool: True if hash matches, False otherwise
    """
    actual_hash = hash_data(data, algorithm)
    return hmac.compare_digest(actual_hash, expected_hash)


def verify_hmac(data, expected_hmac, secret_key, algorithm=None):
    """
    Verify HMAC for authenticated data integrity
    
    Args:
        data: Data to verify (string or bytes)
        expected_hmac: Expected HMAC value (hex string)
        secret_key: Secret key for HMAC
        algorithm: Hash algorithm to use
        
    Returns:
        bool: True if HMAC matches, False otherwise
    """
    actual_hmac = hmac_hash(data, secret_key, algorithm)
    return hmac.compare_digest(actual_hmac, expected_hmac)
