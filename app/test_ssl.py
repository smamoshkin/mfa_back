import ssl
import certifi

print("SSL certificates path:", certifi.where())
print("SSL available:", ssl.OPENSSL_VERSION)

# Проверь что файл существует
import os
print("Certificate file exists:", os.path.exists(certifi.where()))