#this is just a helper script to test oauth login manually
#!/usr/bin/env python3
import re
import subprocess
import sys
from urllib.parse import urlparse, parse_qs

def extract_oauth_params(redirect_url):
    """Extract code and state from the redirect URL"""
    try:
        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)
        
        code = params.get('code', [None])[0]
        state = params.get('state', [None])[0]
        
        if not code:
            print("❌ No 'code' parameter found in URL")
            return None, None
            
        return code, state
    except Exception as e:
        print(f"❌ Error parsing URL: {e}")
        return None, None

def run_oauth_callback(code, state):
    """Run the OAuth callback curl command"""
    callback_url = "http://localhost:8000/api/v1/auth/callback"
    
    # URL encode the parameters
    code_encoded = code.replace("/", "%2F")
    redirect_uri_encoded = "http%3A%2F%2Flocalhost%3A8000"
    
    curl_cmd = [
        "curl",
        "-X", "POST",
        f"{callback_url}?code={code_encoded}&redirect_uri={redirect_uri_encoded}&state={state}",
        "-H", "accept: application/json"
    ]
    
    print(f"🚀 Running OAuth callback...")
    print(f"Command: {' '.join(curl_cmd)}")
    print()
    
    try:
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=30)
        
        print("📄 Response:")
        print(f"Status Code: {result.returncode}")
        print(f"Response Body: {result.stdout}")
        
        if result.stderr:
            print(f"Error: {result.stderr}")
            
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("❌ Request timed out")
        return False
    except Exception as e:
        print(f"❌ Error running curl: {e}")
        return False

def main():
    print("🔐 OAuth Testing Script")
    print("=" * 50)
    print()
    print("Instructions:")
    print("1. Go to: http://localhost:8000/api/v1/auth/login?redirect_uri=http://localhost:8000/")
    print("2. Complete Google login")
    print("3. Copy the FULL redirect URL you get")
    print("4. Paste it below and press Enter")
    print()
    
    while True:
        try:
            redirect_url = input("📋 Paste the redirect URL here: ").strip()
            
            if not redirect_url:
                print("❌ Empty URL. Please try again.")
                continue
                
            if not redirect_url.startswith("http"):
                print("❌ Invalid URL format. Please paste the full URL starting with http")
                continue
            
            print(f"\n🔍 Extracting parameters from URL...")
            code, state = extract_oauth_params(redirect_url)
            
            if not code:
                print("❌ Could not extract OAuth code. Please try again with a fresh login.")
                continue
                
            print(f"✅ Found code: {code[:20]}...")
            if state:
                print(f"✅ Found state: {state[:20]}...")
            
            print("\n⏰ Running OAuth callback immediately...")
            success = run_oauth_callback(code, state)
            
            if success:
                print("\n🎉 OAuth test completed!")
            else:
                print("\n❌ OAuth test failed. Try with a fresh login URL.")
                
            print("\n" + "=" * 50)
            print("Want to test again? Get a new login URL and paste it, or Ctrl+C to exit")
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            print("Please try again with a fresh login URL")

if __name__ == "__main__":
    main()