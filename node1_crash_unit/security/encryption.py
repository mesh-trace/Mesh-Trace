"""
Data encryption module
Encrypts sensitive crash data for secure transmission
"""

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionManager:
    """Manages encryption keys and operations"""
    
    def __init__(self, key_file="/var/lib/mesh-trace/key.key"):
        """
        Initialize encryption manager
        
        Args:
            key_file: Path to file storing encryption key
        """
        self.key_file = key_file
        self.key = None
        self.cipher = None
        self._load_or_generate_key()
    
    def _load_or_generate_key(self):
        """Load existing key or generate a new one"""
        try:
            if os.path.exists(self.key_file):
                with open(self.key_file, 'rb') as f:
                    self.key = f.read()
            else:
                # Generate new key
                self.key = Fernet.generate_key()
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.key_file), exist_ok=True)
                # Save key (in production, this should be more secure)
                with open(self.key_file, 'wb') as f:
                    f.write(self.key)
            
            self.cipher = Fernet(self.key)
        except Exception as e:
            print(f"Warning: Encryption key management error: {e}")
            # Fallback: generate in-memory key (not persistent)
            self.key = Fernet.generate_key()
            self.cipher = Fernet(self.key)
    
    def encrypt(self, data):
        """
        Encrypt data
        
        Args:
            data: String or bytes data to encrypt
            
        Returns:
            bytes: Encrypted data
        """
        if not self.cipher:
            raise RuntimeError("Encryption cipher not initialized")
        
        if isinstance(data, str):
            data = data.encode('utf-8')
        
        return self.cipher.encrypt(data)
    
    def decrypt(self, encrypted_data):
        """
        Decrypt data
        
        Args:
            encrypted_data: Encrypted bytes data
            
        Returns:
            bytes: Decrypted data
        """
        if not self.cipher:
            raise RuntimeError("Encryption cipher not initialized")
        
        return self.cipher.decrypt(encrypted_data)


# Global encryption instance
_encryption_manager = None


def get_encryption_manager():
    """Get or create global encryption manager instance"""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_data(data, key_file=None):
    """
    Encrypt data using the encryption manager
    
    Args:
        data: Data to encrypt (string or bytes)
        key_file: Optional custom key file path
        
    Returns:
        str: Base64-encoded encrypted data
    """
    if key_file:
        manager = EncryptionManager(key_file)
    else:
        manager = get_encryption_manager()
    
    try:
        encrypted = manager.encrypt(data)
        return base64.b64encode(encrypted).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return None


def decrypt_data(encrypted_data_b64, key_file=None):
    """
    Decrypt data using the encryption manager
    
    Args:
        encrypted_data_b64: Base64-encoded encrypted data
        key_file: Optional custom key file path
        
    Returns:
        bytes: Decrypted data
    """
    if key_file:
        manager = EncryptionManager(key_file)
    else:
        manager = get_encryption_manager()
    
    try:
        encrypted = base64.b64decode(encrypted_data_b64.encode('utf-8'))
        return manager.decrypt(encrypted)
    except Exception as e:
        print(f"Decryption error: {e}")
        return None
