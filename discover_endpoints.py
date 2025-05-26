#!/usr/bin/env python3
"""
Check available endpoints on the MCP SaaS server
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def check_available_endpoints():
    """Check what endpoints are actually available"""
    print("🔍 Checking available endpoints...")
    
    # Get OpenAPI spec to see all endpoints
    try:
        response = requests.get(f"{BASE_URL}/openapi.json")
        if response.status_code == 200:
            openapi_spec = response.json()
            paths = openapi_spec.get("paths", {})
            
            print(f"\n📋 Available endpoints ({len(paths)} total):")
            for path, methods in paths.items():
                method_list = list(methods.keys())
                print(f"  {path} - {', '.join(method_list).upper()}")
            
            # Check for auth endpoints specifically
            auth_endpoints = [p for p in paths if "auth" in p.lower()]
            deployment_endpoints = [p for p in paths if "deploy" in p.lower()]
            mcp_endpoints = [p for p in paths if "mcp" in p.lower()]
            session_endpoints = [p for p in paths if "session" in p.lower()]
            
            print(f"\n🔐 Auth endpoints: {auth_endpoints}")
            print(f"🚀 Deployment endpoints: {deployment_endpoints}")
            print(f"🔌 MCP endpoints: {mcp_endpoints}")
            print(f"📡 Session endpoints: {session_endpoints}")
            
        else:
            print(f"❌ Failed to get OpenAPI spec: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error checking endpoints: {e}")

def test_correct_endpoints():
    """Test the actually available endpoints"""
    print("\n" + "="*50)
    print("🧪 Testing Correct Endpoints")
    print("="*50)
    
    # Test health endpoint (we know this works)
    print("\n1. Health Check:")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Working")
        else:
            print("   ❌ Failed")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test root endpoint
    print("\n2. Root endpoint:")
    try:
        response = requests.get(f"{BASE_URL}/")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Working")
            data = response.json()
            print(f"   Name: {data.get('name')}")
            print(f"   Version: {data.get('version')}")
        else:
            print("   ❌ Failed")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test the login endpoint that works in the code
    print("\n3. Login endpoint (demo credentials):")
    try:
        response = requests.post(f"{BASE_URL}/api/v2/auth/login?username=demo&password=demo")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Working")
            data = response.json()
            print(f"   Success: {data.get('success')}")
            if data.get('success'):
                token = data.get('data', {}).get('access_token')
                print(f"   Token: {token}")
                return token
        else:
            print("   ❌ Failed")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    return None

def test_authenticated_endpoints(token):
    """Test endpoints that require authentication"""
    if not token:
        print("\n⚠️ No token available, skipping authenticated tests")
        return
    
    print("\n4. Testing authenticated endpoints:")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Test sessions endpoint
    try:
        response = requests.get(f"{BASE_URL}/api/v2/sessions", headers=headers)
        print(f"   Sessions endpoint: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Sessions endpoint working")
        else:
            print(f"   ⚠️ Sessions: {response.text[:100]}")
    except Exception as e:
        print(f"   ❌ Sessions error: {e}")
    
    # Test deployment endpoint
    test_deployment = {
        "name": "test-server",
        "source_type": "python",
        "source_data": "aW1wb3J0IGpzb24=",  # base64 encoded "import json"
        "environment_vars": {},
        "dependencies": [],
        "transport": {
            "type": "stdio",
            "config": {},
            "timeout": 30
        }
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/v2/deploy", 
                               json=test_deployment, 
                               headers=headers)
        print(f"   Deploy endpoint: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ Deploy endpoint working")
            data = response.json()
            print(f"   Instance ID: {data.get('data', {}).get('instance_id', 'None')}")
        else:
            print(f"   ⚠️ Deploy: {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ Deploy error: {e}")

def main():
    print("🔍 MCP SaaS Endpoint Discovery")
    print("="*50)
    
    check_available_endpoints()
    token = test_correct_endpoints()
    test_authenticated_endpoints(token)
    
    print("\n" + "="*50)
    print("✅ Endpoint discovery complete!")
    print("💡 Use the interactive docs at http://localhost:8000/docs to explore all features")

if __name__ == "__main__":
    main()
