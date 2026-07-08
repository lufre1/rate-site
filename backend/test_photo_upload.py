#!/usr/bin/env python3
"""Test script for photo upload feature validation."""

import os
import sys
import requests
import base64

# API configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# Create a simple test PNG image as base64
# This is a 2x2 pixel PNG with a red pixel
PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAkSURBVDhPY2RgYGBgAAEYAQABYDCqAAAAAElFTkSuQmCC"

def get_png_bytes():
    """Get PNG image as bytes from base64."""
    return base64.b64decode(PNG_BASE64)


def check_photo_url_column():
    """Test 1: Check if photo_url column exists in ratings table."""
    print("\n" + "="*60)
    print("TEST 1: Check photo_url column in ratings table")
    print("="*60)
    
    try:
        # Check via database directly
        from database import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='ratings' AND column_name='photo_url'"
            ))
            row = result.fetchone()
            
            if row:
                print("✓ PASS: photo_url column exists in ratings table")
                return True
            else:
                print("✗ FAIL: photo_url column NOT found in ratings table")
                return False
    except Exception as e:
        print(f"✗ FAIL: Exception checking database: {e}")
        return False


def get_first_meal_id():
    """Get the first available meal ID for testing."""
    from database import SessionLocal
    from database import Meal
    
    db = SessionLocal()
    try:
        meal = db.query(Meal).first()
        if meal:
            return meal.id
        return None
    finally:
        db.close()


def create_test_image_file(filepath):
    """Create a test PNG file."""
    with open(filepath, 'wb') as f:
        f.write(get_png_bytes())
    return filepath


def test_photo_upload():
    """Test 2: Test the photo upload endpoint."""
    print("\n" + "="*60)
    print("TEST 2: Photo upload endpoint")
    print("="*60)
    
    meal_id = get_first_meal_id()
    if not meal_id:
        print("✗ FAIL: No meal found to test with")
        return False
    
    # Create a temporary test image
    import tempfile
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False) as f:
        temp_image = f.name
        create_test_image_file(temp_image)
    
    try:
        url = f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings-with-photo"

        # Test with valid PNG
        files = {'photo': ('test.png', open(temp_image, 'rb'), 'image/png')}
        data = {'rating': 5, 'comment': 'Test comment'}
        
        response = requests.post(url, data=data, files=files, timeout=10)
        
        if response.status_code == 201:
            result = response.json()
            print(f"✓ PASS: Photo upload successful (status: {response.status_code})")
            print(f"  Response: {result}")
            # Verify photo_url is returned
            if 'photo_url' in result and result['photo_url']:
                print(f"  ✓ photo_url returned: {result['photo_url']}")
            else:
                print(f"  ✗ FAIL: No photo_url in response")
                return False
            # Verify the rating and comment form fields were actually persisted
            if result.get('rating') != 5:
                print(f"  ✗ FAIL: rating not persisted correctly (got {result.get('rating')})")
                return False
            if result.get('comment') != 'Test comment':
                print(f"  ✗ FAIL: comment not persisted correctly (got {result.get('comment')!r})")
                return False
            print("  ✓ rating and comment persisted correctly")
            return True
        else:
            print(f"✗ FAIL: Photo upload failed with status {response.status_code}")
            print(f"  Response: {response.text}")
            return False
    except Exception as e:
        print(f"✗ FAIL: Exception during photo upload: {e}")
        return False
    finally:
        if os.path.exists(temp_image):
            os.unlink(temp_image)


def test_invalid_file_type():
    """Test 3: Test rejection of invalid file types."""
    print("\n" + "="*60)
    print("TEST 3: Invalid file type rejection")
    print("="*60)
    
    meal_id = get_first_meal_id()
    if not meal_id:
        print("✗ FAIL: No meal found to test with")
        return False
    
    # Create a temporary text file (not an image)
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        temp_file = f.name
        f.write("This is not an image")
    
    try:
        url = f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings-with-photo"

        files = {'photo': ('test.txt', open(temp_file, 'rb'), 'text/plain')}
        data = {'rating': 4, 'comment': 'Testing invalid file type'}
        
        response = requests.post(url, data=data, files=files, timeout=10)
        
        if response.status_code == 400:
            print(f"✓ PASS: Invalid file type rejected (status: {response.status_code})")
            print(f"  Response: {response.json().get('detail', 'No detail')}")
            return True
        else:
            print(f"✗ FAIL: Invalid file type was accepted (status: {response.status_code})")
            print(f"  Response: {response.text}")
            return False
    except Exception as e:
        print(f"✗ FAIL: Exception during invalid file test: {e}")
        return False
    finally:
        if os.path.exists(temp_file):
            os.unlink(temp_file)


def test_photo_retrieval():
    """Test 4: Test the photo retrieval endpoint."""
    print("\n" + "="*60)
    print("TEST 4: Photo retrieval endpoint")
    print("="*60)
    
    meal_id = get_first_meal_id()
    if not meal_id:
        print("✗ FAIL: No meal found to test with")
        return False
    
    # First upload a photo
    import tempfile
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False) as f:
        temp_image = f.name
        create_test_image_file(temp_image)
    
    try:
        # Upload a photo
        url = f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings-with-photo"
        files = {'photo': ('retrieval_test.png', open(temp_image, 'rb'), 'image/png')}
        data = {'rating': 3, 'comment': 'Photo for retrieval test'}
        
        response = requests.post(url, data=data, files=files, timeout=10)
        
        if response.status_code != 201:
            print(f"✗ FAIL: Could not upload photo for retrieval test: {response.status_code}")
            return False
        
        upload_result = response.json()
        rating_id = upload_result.get('id')
        photo_url = upload_result.get('photo_url')
        
        if not photo_url:
            print("✗ FAIL: No photo_url returned from upload")
            return False
        
        print(f"  Uploaded photo at: {photo_url}")
        
        # Test direct rating endpoint
        rating_url = f"{API_BASE_URL}/api/v1/ratings/{rating_id}"
        response = requests.get(rating_url, timeout=10)
        
        if response.status_code == 200:
            rating_data = response.json()
            if rating_data.get('photo_url') == photo_url:
                print(f"✓ PASS: Rating endpoint returns photo_url: {photo_url}")
            else:
                print(f"✗ FAIL: photo_url mismatch in rating endpoint")
                return False
        else:
            print(f"✗ FAIL: Rating endpoint failed: {response.status_code}")
            return False
        
        # Test photos-for-meal endpoint
        photos_url = f"{API_BASE_URL}/api/v1/meals/{meal_id}/photos"
        response = requests.get(photos_url, timeout=10)
        
        if response.status_code == 200:
            photos_data = response.json()
            photo_found = any(p.get('photo_url') == photo_url for p in photos_data)
            if photo_found:
                print(f"✓ PASS: Photos endpoint returns photo for meal")
            else:
                print(f"✗ FAIL: Photos endpoint does not contain uploaded photo")
                return False
        else:
            print(f"✗ FAIL: Photos endpoint failed: {response.status_code}")
            return False
        
        return True
    except Exception as e:
        print(f"✗ FAIL: Exception during photo retrieval test: {e}")
        return False
    finally:
        if os.path.exists(temp_image):
            os.unlink(temp_image)


def test_serving_photos():
    """Test 5: Test serving photos."""
    print("\n" + "="*60)
    print("TEST 5: Serving photos")
    print("="*60)
    
    meal_id = get_first_meal_id()
    if not meal_id:
        print("✗ FAIL: No meal found to test with")
        return False
    
    # Upload a photo
    import tempfile
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False) as f:
        temp_image = f.name
        create_test_image_file(temp_image)
    
    try:
        # Upload a photo
        url = f"{API_BASE_URL}/api/v1/meals/{meal_id}/ratings-with-photo"
        files = {'photo': ('serving_test.png', open(temp_image, 'rb'), 'image/png')}
        data = {'rating': 4, 'comment': 'Photo for serving test'}
        
        response = requests.post(url, data=data, files=files, timeout=10)
        
        if response.status_code != 201:
            print(f"✗ FAIL: Could not upload photo for serving test: {response.status_code}")
            return False
        
        upload_result = response.json()
        photo_url = upload_result.get('photo_url')
        
        if not photo_url:
            print("✗ FAIL: No photo_url returned from upload")
            return False
        
        print(f"  Photo URL: {photo_url}")
        
        # Extract filename from photo_url (e.g., /uploads/test123.png -> test123.png)
        filename = photo_url.split('/')[-1]
        
        # Test serving the photo directly
        serve_url = f"{API_BASE_URL}{photo_url}"
        response = requests.get(serve_url, timeout=10, stream=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            if 'image/png' in content_type or 'image/jpeg' in content_type:
                print(f"✓ PASS: Photo serving successful (status: {response.status_code})")
                print(f"  Content-Type: {content_type}")
                # Verify content is actually an image
                content = response.content
                if content.startswith(b'\x89PNG'):
                    print("  ✓ Verified: Content is valid PNG image")
                return True
            else:
                print(f"✗ FAIL: Wrong Content-Type: {content_type}")
                return False
        else:
            print(f"✗ FAIL: Photo serving failed with status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ FAIL: Exception during photo serving test: {e}")
        return False
    finally:
        if os.path.exists(temp_image):
            os.unlink(temp_image)


def main():
    """Run all tests."""
    # Check if API is available
    print("\n" + "="*60)
    print("PHOTO UPLOAD FEATURE VALIDATION")
    print("="*60)
    print(f"API Base URL: {API_BASE_URL}")
    
    # Check if API is reachable
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/mensas", timeout=5)
        if response.status_code != 200:
            print(f"✗ FAIL: API not responding correctly: {response.status_code}")
            sys.exit(1)
        print("✓ PASS: API is reachable")
    except Exception as e:
        print(f"✗ FAIL: Cannot connect to API: {e}")
        print("  Make sure the backend service is running.")
        sys.exit(1)
    
    # Run tests
    results = []
    
    results.append(("Photo URL column check", check_photo_url_column()))
    results.append(("Photo upload endpoint", test_photo_upload()))
    results.append(("Invalid file type rejection", test_invalid_file_type()))
    results.append(("Photo retrieval endpoint", test_photo_retrieval()))
    results.append(("Serving photos", test_serving_photos()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())