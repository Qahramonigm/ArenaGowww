import os
import sys
import django
import urllib.request
import http.cookiejar

sys.path.insert(0, r'c:\Users\User\Desktop\ArenaGo\blog')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog.settings')
django.setup()

# Test the page through Django's test client
from django.test import Client

client = Client()

# First, log in
response = client.post('/support/agent/login/', {
    'username': 'testadmin',
    'password': 'testpass123'
})

print(f"Login response status: {response.status_code}")

# Now try to access the panel
response = client.get('/support/agent/')
print(f"Panel response status: {response.status_code}")
print(f"Response content type: {response.get('content-type')}")

# Check if it's proper HTML
content = response.content.decode()
if '<!DOCTYPE html>' in content:
    print("✓ Response contains proper HTML DOCTYPE")
if '<html' in content:
    print("✓ Response contains <html> tag")
if 'Support Agent Panel' in content:
    print("✓ Response contains 'Support Agent Panel' title")
    
print(f"\nFirst 400 characters of response:")
print(content[:400])
