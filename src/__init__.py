# Use the Windows/macOS certificate store for HTTPS (needed behind filtered internet
# providers, and with Python 3.13's stricter certificate checks).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
