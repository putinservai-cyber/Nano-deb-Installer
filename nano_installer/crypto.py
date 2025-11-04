from cryptography.fernet import Fernet, InvalidToken

def encrypt_data(data: str, key: bytes) -> str:
    """
    Encrypts data using Fernet (AES-128-CBC with HMAC-SHA256).
    Returns a URL-safe, base64-encoded string.
    """
    f = Fernet(key)
    encrypted_data = f.encrypt(data.encode('utf-8'))
    return encrypted_data.decode('utf-8')

def decrypt_data(encrypted_data: str, key: bytes) -> str | None:
    """
    Decrypts data encrypted with Fernet.
    Returns the original string, or None if decryption fails (e.g., invalid key or tampered data).
    """
    f = Fernet(key)
    try:
        decrypted_bytes = f.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken:
        # This error occurs if the key is wrong or the data has been tampered with.
        return None

def generate_key() -> bytes:
    """
    Generates a new Fernet key.
    """
    return Fernet.generate_key()

def simple_xor_decrypt(data: str, key: bytes) -> str:
    """
    Decrypts a hex-encoded string using a simple XOR cipher.
    """
    # Convert hex string to bytes
    encrypted_bytes = bytes.fromhex(data)
    key_len = len(key)
    decrypted_bytes = bytearray()
    for i, byte in enumerate(encrypted_bytes):
        decrypted_bytes.append(byte ^ key[i % key_len])
    return decrypted_bytes.decode('utf-8')


# A hardcoded key for demonstration. In a real application, this should be
# stored securely (e.g., in a config file with strict permissions, environment variable,
# or a system keyring) and not in the source code.
ENCRYPTION_KEY = b'3Zf5_Vw9wX8yJ2a6bC4dE7gH1iK0lO3mP5qR8tUvYw='

# Example usage (for development/testing)
# encrypted_api_key = encrypt_data("your-virustotal-api-key-here", ENCRYPTION_KEY)
# decrypted_api_key = decrypt_data(encrypted_api_key, ENCRYPTION_KEY)